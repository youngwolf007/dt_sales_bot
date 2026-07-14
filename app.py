import json
import uuid

import gradio as gr
from agents import (
    InputGuardrailTripwireTriggered,
    OutputGuardrailTripwireTriggered,
    Runner,
    SQLiteSession,
    gen_trace_id,
    trace,
)
from openai import RateLimitError
from openai.types.responses import ResponseTextDeltaEvent

from agents_def.sales_agent import gemini_sales_agent, sales_agent
from auth import generate_and_send_otp, verify_otp
from context import SalesContext
from tools.email_tool import EMAIL_RE

INPUT_GUARDRAIL_MESSAGES = {
    "pii_input_guardrail": (
        "For your security, please don't share sensitive details like card "
        "numbers, passwords, or ID numbers here — I don't need that. Let's "
        "get back to your business requirements."
    ),
    "on_topic_guardrail": (
        "I'm here to help with Deutsche Telekom business solutions — could "
        "you rephrase that as a question about your business needs?"
    ),
}
DEFAULT_INPUT_GUARDRAIL_MESSAGE = "Sorry, I can't help with that here — let's get back to your business needs."
OUTPUT_GUARDRAIL_MESSAGE = (
    "\n\n⚠️ I need to correct part of that reply — please disregard any link "
    "above I can't verify, and feel free to ask me again."
)
CONNECTION_TROUBLE_MESSAGE = "I'm having trouble connecting right now — please try again in a moment."

TITLE = "Deutsche Telekom — Business Solutions Advisor"
DESCRIPTION = (
    "Tell me about your business and I'll help you find the right Deutsche Telekom "
    "solutions — mobile & fleet, fixed network, IoT, cloud & security, and more. "
    "I can email you a written proposal once we've found a good fit."
)

TOOL_STATUS_LABELS = {
    "research_dt_solutions": "🔎 Researching Deutsche Telekom solutions...",
    "send_proposal_email": "📧 Preparing your proposal and PDF brochure...",
}

GREETING_OPTIONS = [
    {"label": "Mobile", "value": "I'm interested in mobile & fleet connectivity solutions."},
    {"label": "Cloud", "value": "I'm interested in cloud solutions."},
    {"label": "IoT", "value": "I'm interested in IoT & M2M solutions."},
    {"label": "Security", "value": "I'm interested in security solutions."},
]


def _build_greeting_chatbot() -> gr.Chatbot:
    """A fresh gr.Chatbot pre-seeded with a greeting message and clickable
    topic options — clicking one sends its value as the next user message,
    same as typing it (Gradio's built-in ChatMessage.options + option_select
    behavior, no custom wiring needed)."""
    greeting = gr.ChatMessage(
        role="assistant",
        content="Hi! How can I help you today?",
        options=GREETING_OPTIONS,
    )
    return gr.Chatbot(value=[greeting], show_label=False)

# One SQLiteSession per login (a fresh id is minted each time someone verifies
# an OTP — see handle_verify_otp), not per email — so memory lasts for the
# current sign-in only and a later, unrelated visit never resumes an old,
# possibly-incomplete conversation. The id is namespaced under the email
# purely so rows stay traceable to a user in the DB.
_sessions: dict[str, SQLiteSession] = {}


def _new_session_id(email: str) -> str:
    return f"{email}::{uuid.uuid4().hex[:12]}"


def _get_session(session_id: str) -> SQLiteSession:
    if session_id not in _sessions:
        _sessions[session_id] = SQLiteSession(session_id, "dt_sales_bot_sessions.db")
    return _sessions[session_id]


def _parse_quick_reply_options(raw_item) -> list[str] | None:
    try:
        args = json.loads(getattr(raw_item, "arguments", "") or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    options = [str(opt).strip() for opt in (args.get("options") or []) if str(opt).strip()]
    return options[:4] or None


def _chunk_text(chunk: str | gr.ChatMessage | None) -> str:
    if isinstance(chunk, gr.ChatMessage):
        return chunk.content
    return chunk or ""


def _append_warning(base: str, warning: str) -> str:
    return f"{base}\n\n⚠️ {warning}" if base else f"⚠️ {warning}"


async def _drop_dangling_user_turn(session: SQLiteSession) -> None:
    """The Agents SDK persists a turn's user message to the session as soon as
    the run starts, before the model produces any reply. If the run then
    errors out before completing, that message (which may be a confirmation
    like "yes, send it") is left in the session with no assistant response —
    a later turn within the same login would see it as still outstanding and
    could act on it (e.g. re-attempt a send the user thinks never happened).
    Since the user already saw a failure message and can just retry, drop the
    orphaned message rather than let it linger."""
    items = await session.get_items(limit=1)
    if items and items[-1].get("role") == "user":
        await session.pop_item()


async def _stream_turn(agent, message: str, session, context, trace_id: str, verified_email: str, session_id: str):
    """Runs one turn against `agent`, yielding streaming chunks (str, or a
    final gr.ChatMessage if the agent offered quick-reply options). Shared by
    both the primary agent and the Gemini fallback so they don't duplicate
    this logic — raises on failure so the caller decides whether to retry."""
    response = ""
    status = ""
    quick_reply_options: list[str] | None = None

    with trace(f"DT Sales Bot — {verified_email}", trace_id=trace_id, group_id=session_id):
        result = Runner.run_streamed(agent, input=message, session=session, context=context)
        async for event in result.stream_events():
            if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                if event.data.delta:
                    response += event.data.delta
                    yield status + response
            elif event.type == "run_item_stream_event":
                item = event.item
                if getattr(item, "type", "") == "tool_call_item":
                    tool_name = getattr(item.raw_item, "name", "")
                    if tool_name == "offer_quick_replies":
                        quick_reply_options = _parse_quick_reply_options(item.raw_item)
                    label = TOOL_STATUS_LABELS.get(tool_name)
                    if label:
                        status = f"_{label}_\n\n"
                        yield status + response

    if quick_reply_options:
        yield gr.ChatMessage(
            role="assistant",
            content=response,
            options=[{"value": opt} for opt in quick_reply_options],
        )
    else:
        yield response


async def chat(
    message: str,
    history: list[dict],
    verified_email: str,
    verified_name: str,
    verified_company: str,
    session_id: str,
):
    session = _get_session(session_id)
    context = SalesContext(
        customer_email=verified_email,
        customer_name=verified_name,
        customer_company=verified_company,
    )

    trace_id = gen_trace_id()
    print(f"Trace: https://platform.openai.com/traces/trace?trace_id={trace_id}")

    last_chunk: str | gr.ChatMessage | None = None
    try:
        async for chunk in _stream_turn(sales_agent, message, session, context, trace_id, verified_email, session_id):
            last_chunk = chunk
            yield chunk
        return
    except InputGuardrailTripwireTriggered as exc:
        name = exc.guardrail_result.guardrail.get_name()
        print(f"Input guardrail tripped: {name} — {exc.guardrail_result.output.output_info}")
        yield INPUT_GUARDRAIL_MESSAGES.get(name, DEFAULT_INPUT_GUARDRAIL_MESSAGE)
        return
    except OutputGuardrailTripwireTriggered as exc:
        print(f"Output guardrail tripped: {exc.guardrail_result.output.output_info}")
        yield _chunk_text(last_chunk) + OUTPUT_GUARDRAIL_MESSAGE
        return
    except RateLimitError as exc:
        print(f"OpenAI rate-limited: {exc}")
        if last_chunk is None and gemini_sales_agent is not None:
            print("No output streamed yet — retrying this turn via Gemini fallback.")
            try:
                async for chunk in _stream_turn(
                    gemini_sales_agent, message, session, context, trace_id, verified_email, session_id
                ):
                    yield chunk
                return
            except Exception as exc2:  # noqa: BLE001 - fallback also failed, fall through to the generic message
                print(f"Gemini fallback also failed: {exc2}")
        await _drop_dangling_user_turn(session)
        yield _append_warning(_chunk_text(last_chunk), CONNECTION_TROUBLE_MESSAGE)
        return
    except Exception as exc:  # noqa: BLE001 - never let a raw exception crash the chat turn
        print(f"Unexpected error during chat turn: {exc}")
        await _drop_dangling_user_turn(session)
        yield _append_warning(_chunk_text(last_chunk), CONNECTION_TROUBLE_MESSAGE)
        return


def handle_send_otp(email: str, name: str, company: str):
    email = (email or "").strip()
    name = (name or "").strip()
    company = (company or "").strip()

    if not EMAIL_RE.match(email):
        return (
            None,
            None,
            None,
            "❌ Please enter a valid email address.",
            gr.update(visible=False),
            gr.update(visible=False),
        )
    if not name or not company:
        return (
            None,
            None,
            None,
            "❌ Please enter your name and company name.",
            gr.update(visible=False),
            gr.update(visible=False),
        )

    error = generate_and_send_otp(email)
    if error:
        return None, None, None, f"❌ {error}", gr.update(visible=False), gr.update(visible=False)

    return (
        email,
        name,
        company,
        f"✅ Code sent to {email}. Check your inbox (and spam folder).",
        gr.update(visible=True),
        gr.update(visible=True),
    )


def handle_verify_otp(pending_email: str, pending_name: str, pending_company: str, code: str):
    if not pending_email:
        return (
            None,
            None,
            None,
            None,
            "❌ Please request a code first.",
            gr.update(visible=True),
            gr.update(visible=False),
        )

    ok, error = verify_otp(pending_email, (code or "").strip())
    if not ok:
        return None, None, None, None, f"❌ {error}", gr.update(visible=True), gr.update(visible=False)

    return (
        pending_email,
        pending_name,
        pending_company,
        _new_session_id(pending_email),
        "",
        gr.update(visible=False),
        gr.update(visible=True),
    )


with gr.Blocks(title=TITLE) as demo:
    verified_email = gr.State(None)
    verified_name = gr.State(None)
    verified_company = gr.State(None)
    session_id = gr.State(None)
    pending_email = gr.State(None)
    pending_name = gr.State(None)
    pending_company = gr.State(None)

    gr.Markdown(f"# {TITLE}")

    with gr.Group(visible=True) as login_group:
        gr.Markdown("### Sign in to continue\nTell us a bit about yourself — we'll send you a one-time code.")
        name_box = gr.Textbox(label="Full name", placeholder="Jane Doe")
        company_box = gr.Textbox(label="Company name", placeholder="Acme Corp")
        email_box = gr.Textbox(label="Email address", placeholder="you@company.com")
        send_otp_btn = gr.Button("Send code")
        login_status = gr.Markdown("")
        otp_box = gr.Textbox(label="Enter the 6-digit code", visible=False)
        verify_btn = gr.Button("Verify", visible=False)

    with gr.Group(visible=False) as chat_group:
        gr.Markdown(DESCRIPTION)
        gr.ChatInterface(
            chat,
            additional_inputs=[verified_email, verified_name, verified_company, session_id],
            chatbot=_build_greeting_chatbot(),
        )

    send_otp_btn.click(
        handle_send_otp,
        inputs=[email_box, name_box, company_box],
        outputs=[pending_email, pending_name, pending_company, login_status, otp_box, verify_btn],
    )
    verify_btn.click(
        handle_verify_otp,
        inputs=[pending_email, pending_name, pending_company, otp_box],
        outputs=[
            verified_email,
            verified_name,
            verified_company,
            session_id,
            login_status,
            login_group,
            chat_group,
        ],
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
