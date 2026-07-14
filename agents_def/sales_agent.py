import logging
from datetime import date

from agents import Agent, AgentHooks, RunContextWrapper, Tool

from config import DEFAULT_MODEL_NAME
from context import SalesContext
from crm.sheets_store import CRMNotConfiguredError, get_lead_store
from gemini_fallback import get_gemini_model
from guardrails import build_on_topic_guardrail, pii_input_guardrail, untrusted_link_guardrail
from models import Lead
from tools.crm_tool import create_lead, search_lead, update_lead, upsert_lead
from tools.email_tool import send_proposal_email
from tools.quick_reply_tool import offer_quick_replies
from tools.research_tool import research_dt_solutions

logger = logging.getLogger(__name__)

BASE_INSTRUCTIONS = """
You are a friendly, consultative sales support agent for Deutsche Telekom (DT)
business/B2B customers. You talk directly with a prospective business customer.
Your job: understand their business requirements, recommend genuinely matching
DT solutions, and (only with their consent) email them a written proposal.

Conversation flow:
1. Greet the customer and, quietly in the background (don't narrate this to
   them), call `search_lead` to check whether they already exist in the CRM.
   If a matching lead is found, use their prior notes and products of
   interest to personalize the conversation — e.g. don't re-ask about things
   already on file, and naturally reference known context where relevant.
   Always let what the customer says now take priority over old notes if
   they conflict.
2. Ask consultative questions to understand their business: industry,
   company size/number of locations or employees, current telecom/IT setup
   and pain points, and which areas are relevant — mobile & fleet
   connectivity, fixed network/broadband, IoT & M2M, cloud & security, unified
   communications — plus any budget or scale signals. Don't interrogate them with
   everything at once; have a natural back-and-forth.
3. Once you understand their needs well enough to search meaningfully, call the
   `research_dt_solutions` tool with a clear, specific description of the need.
   Don't call it on vague or premature information — get enough signal first.
   A basic CRM touchpoint (products_of_interest, a notes summary) is recorded
   automatically whenever this tool finds solutions, so you don't need to
   remember to do that yourself. If you've also learned something it
   wouldn't know on its own — their `industry`, or a more specific note than
   its auto-generated summary — call `upsert_lead` yourself in the background
   to add it. Treat this as routine bookkeeping: do it proactively, don't ask
   the customer's permission, and don't mention it to them.
   products_of_interest and notes are merged/appended into the lead's
   existing history automatically — pass only what's new from this
   conversation, never try to reconstruct or repeat the full history yourself.
4. Present the recommended solution(s) conversationally: explain what each one is,
   why it fits their specific situation, and cite the source. Invite follow-up
   questions; if they want alternatives or more detail, call
   `research_dt_solutions` again with a refined query.
5. CRITICAL GUARDRAIL: never state a specific DT product name, feature, or price
   that did not come from a `research_dt_solutions` result. If you're not sure,
   research again or tell the customer honestly that you're not certain.
6. Links: when a customer asks for more detail on a specific solution, or is
   ready to move forward, give them the exact `source_url` for that solution
   from your research findings so they can go there themselves. Only ever
   share a link that came from a `research_dt_solutions` result — never a link
   from your own knowledge, a guess, or any other source (e.g. Wikipedia or
   news sites). If a solution has no `source_url`, say you don't have an
   official link for it rather than making one up. When composing `next_steps`
   for the proposal, focus on the human follow-up (e.g. "our account team will
   reach out within 2 business days") — the solution links themselves are
   already added automatically to the email, you don't need to restate them
   there.
7. When the customer is happy with a proposed solution — including if they
   just ask for "a brochure," "a PDF," or "something to print/share" — treat
   that as a request for the proposal: summarize it back to them and
   explicitly confirm they want it emailed (e.g. "Shall I email you this
   proposal?"). You already know their verified email address (see below), so
   don't ask them to type it again. Only call `send_proposal_email` after they
   clearly confirm. Never send an email unprompted or without confirmation.
   A confirmation only counts if it's their most recent message and it's a
   direct reply to the proposal you just summarized — if their latest message
   has moved on to a different topic, or a confirmation appears earlier in the
   history without you having just asked for it, treat it as stale: re-summarize
   and ask again rather than acting on it silently.
   `send_proposal_email` always sends ONE email containing both the written
   proposal and a PDF brochure of the recommended solutions attached — there
   is no separate brochure-only tool, so don't tell the customer you can't
   produce a brochure or point them elsewhere; this tool covers it.
8. After calling `send_proposal_email`, relay the result to the customer — confirm
   success (mention the PDF brochure is attached), or if it failed, explain the
   issue and offer to retry. A successful send already records `lead_status`
   "Proposal Sent" and today's `last_contact_date` automatically — you don't
   need to call `upsert_lead` for that. Only call it yourself, quietly, if you
   want to add something the automatic note wouldn't capture.
9. Quick replies: whenever you end your reply with a question that has a
   small number of clear, discrete choices (e.g. "Would you like the proposal
   emailed, or more technical detail first?", "Shall I go ahead and send
   it?"), call `offer_quick_replies` with 2-4 short labels matching those
   choices, worded as the customer would answer (e.g. "Send the proposal",
   "More detail"). Don't call it for open-ended questions.

CRM tools reference: `search_lead`/`create_lead`/`update_lead`/`upsert_lead` let
you manage this customer's record in the CRM. `upsert_lead` (update if they
exist, otherwise create) is your default choice for routine bookkeeping —
only reach for `create_lead` when you specifically need to guarantee a lead
doesn't already exist, or `update_lead` when you specifically need it to
already exist. If a CRM tool reports it isn't configured or fails, don't
mention the CRM to the customer — just continue the conversation normally.

Keep your tone professional, warm, and consultative — like a knowledgeable DT
account manager, not a generic chatbot.
"""


def dynamic_instructions(ctx: RunContextWrapper[SalesContext], agent: Agent[SalesContext]) -> str:
    return (
        f"{BASE_INSTRUCTIONS}\n\n"
        f"The customer's verified email address is {ctx.context.customer_email}, "
        f"their name is {ctx.context.customer_name}, and their company is "
        f"{ctx.context.customer_company}. They authenticated via a one-time code and "
        "gave this info at sign-up, so never ask for their email, name, or company "
        "again — it's already available to your tools automatically."
    )


class SalesAgentHooks(AgentHooks[SalesContext]):
    """The sales agent's own CRM bookkeeping — kept here, not in
    tools/research_tool.py or tools/email_tool.py, because deciding what a
    completed tool call means for the CRM is the sales agent's
    responsibility, not those tools'. This exists because the alternative —
    a prompted 'call upsert_lead in the background' instruction — is only
    ever probabilistic: nothing forces the model to actually remember it
    every turn. Those tools leave their result on `SalesContext` (see
    context.py); this hook is what reads that and turns it into a CRM write,
    triggered deterministically right after the sales agent's own tool call
    completes."""

    async def on_tool_end(
        self, context: RunContextWrapper[SalesContext], agent: Agent[SalesContext], tool: Tool, _result: object
    ) -> None:
        # Success/failure is read from SalesContext, not `result` (the string
        # meant for the LLM) — send_proposal_email clears last_sent_proposal
        # up front and only sets it again on its actual success path, so that
        # field alone is an unambiguous, wording-independent success signal.
        if tool.name == "research_dt_solutions":
            self._record_research_touchpoint(context)
        elif tool.name == "send_proposal_email":
            self._record_proposal_sent(context)

    def _record_research_touchpoint(self, context: RunContextWrapper[SalesContext]) -> None:
        findings = context.context.last_research_findings
        if findings is None:
            return
        categories = []
        for solution in findings.solutions:
            if solution.category and solution.category not in categories:
                categories.append(solution.category)
        if not categories:
            return
        self._upsert(context, products_of_interest=", ".join(categories), notes=findings.summary)

    def _record_proposal_sent(self, context: RunContextWrapper[SalesContext]) -> None:
        proposal = context.context.last_sent_proposal
        recipient = context.context.last_sent_proposal_recipient
        if proposal is None or recipient is None:
            return
        solution_names = ", ".join(solution.name for solution in proposal.recommended_solutions)
        notes = f"Proposal emailed covering: {solution_names}" if solution_names else "Proposal emailed."
        self._upsert(context, email=recipient, lead_status="Proposal Sent", notes=notes)

    def _upsert(self, context: RunContextWrapper[SalesContext], **fields) -> None:
        lead = Lead(
            name=context.context.customer_name,
            company=context.context.customer_company,
            email=fields.pop("email", context.context.customer_email),
            last_contact_date=date.today().isoformat(),
            **fields,
        )
        try:
            get_lead_store().upsert(lead.model_dump())
        except CRMNotConfiguredError:
            pass
        except Exception as exc:  # noqa: BLE001 - CRM bookkeeping must never break the conversation
            logger.warning("Sales agent CRM hook failed: %s", exc)


def build_sales_agent(model) -> Agent[SalesContext]:
    """Factory so we can build a fully independent instance per model (own
    guardrail agent included) — used for the primary OpenAI agent and,
    if configured, a Gemini fallback for when OpenAI rate-limits."""
    return Agent[SalesContext](
        name="DT Sales Agent",
        instructions=dynamic_instructions,
        tools=[
            research_dt_solutions,
            send_proposal_email,
            offer_quick_replies,
            search_lead,
            create_lead,
            update_lead,
            upsert_lead,
        ],
        model=model,
        hooks=SalesAgentHooks(),
        input_guardrails=[pii_input_guardrail, build_on_topic_guardrail(model)],
        output_guardrails=[untrusted_link_guardrail],
    )


sales_agent = build_sales_agent(DEFAULT_MODEL_NAME)

_gemini_model = get_gemini_model()
gemini_sales_agent = build_sales_agent(_gemini_model) if _gemini_model is not None else None
