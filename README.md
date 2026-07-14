---
title: DT Sales Bot
emoji: 📡
colorFrom: pink
colorTo: blue
sdk: gradio
sdk_version: 6.20.0
app_file: app.py
pinned: false
---

# DT Sales Support Chatbot

A multi-agent sales support chatbot for Deutsche Telekom (DT) business customers,
built with the OpenAI Agents SDK.

- **Sales Agent** — talks to the customer, gathers their business requirements,
  presents recommended DT solutions, and (with explicit consent) emails a
  proposal.
- **Researcher Agent** — exposed to the Sales Agent as a tool
  (`research_dt_solutions`). Researches broadly but cites narrowly: it can
  search the web and fetch *any* page (the customer's own site, industry
  background, comparison articles, etc.) to understand the business need in
  depth, but a solution's `source_url` is only ever allowed to be a genuine
  Deutsche Telekom / T-Systems / Vonage page — background material is never
  cited as a source. It remembers earlier findings for the same customer and
  returns structured, sourced findings.

The customer's verified email flows to both agents' tools via a typed
`context` object (`context.py`), not by editing the chat transcript — so it's
never re-asked for and never pollutes stored conversation history.

## Setup

```bash
cd dt_sales_bot
uv sync            # or: pip install -e .
cp .env.example .env
# then fill in OPENAI_API_KEY and SMTP credentials in .env
```

`EMAIL_APP_PASSWORD` should be an app password (e.g. a Gmail App Password), not
your regular account password.

`GEMINI_API_KEY` is optional — see "Rate-limit fallback" below.

## Run

```bash
uv run app.py       # or: python app.py
```

Open the local Gradio URL that's printed. Conversation memory persists per
verified email (backed by `dt_sales_bot_sessions.db`, an on-disk SQLite
session).

## Login

Visitors must verify their email with a one-time code before reaching the
chatbot: enter an email, get a 6-digit code by email (5-minute expiry, 5
attempts), enter it to unlock the chat. The code store is in-memory
(`auth.py`) — it resets on app restart and only works for a single process,
which is fine for a hackathon demo but not for a multi-instance deployment.

## Quick-reply buttons

Two sources of clickable quick-reply buttons, both built on Gradio's native
`gr.ChatMessage(options=[...])` (clicking sends the option's value as the next
user message, exactly as if typed — no custom event wiring needed):

- **Greeting**: the chat opens with "Hi! How can I help you today?" and four
  topic buttons (Mobile / Cloud / IoT / Security) — `app.py`'s
  `_build_greeting_chatbot`. This only seeds the *client-side* initial
  display; it isn't part of the agent's own session history.
- **Mid-conversation**: the Sales Agent has an `offer_quick_replies` tool
  (`tools/quick_reply_tool.py`) it's instructed to call whenever it ends a
  reply with a question that has a small set of discrete answers (e.g. "send
  the proposal, or more detail first?"). `app.py`'s `chat()` detects that
  tool call mid-stream, parses its `options` argument, and yields a final
  `gr.ChatMessage(content=..., options=[...])` instead of plain text so the
  reply shows clickable buttons. This is instruction-following, not a
  deterministic code path — the model calls the tool when it judges a
  question has discrete choices, which in practice is *likely* but not
  guaranteed on every qualifying turn.

## How it works

1. The Sales Agent asks about the customer's industry, size, current telecom
   setup, and pain points.
2. Once it has enough signal, it calls `research_dt_solutions`, which runs the
   Researcher Agent (web search + page fetch, with its own memory of this
   customer's prior research) to find real DT solutions.
3. The Sales Agent presents the findings, cites sources, and can re-research for
   alternatives on request. It will not state a DT product fact that didn't come
   from a research result.
4. When the customer agrees on a solution (or simply asks for "a brochure" /
   "a PDF" — that's treated as the same request), the Sales Agent confirms and
   calls `send_proposal_email`, which sends **one** email to their verified
   address: the written proposal in the body, plus a branded PDF brochure of
   the recommended solutions attached (`tools/brochure_tool.py`, via
   `xhtml2pdf` — pure Python, no native/system dependencies like WeasyPrint
   would need). There is no separate brochure-only tool/email — the two used
   to be sent as two separate emails, which was confusing, so brochure
   generation is now folded into the one proposal send. If PDF generation
   fails, the email still sends without the attachment rather than blocking
   entirely, and the failure is reported back to the agent to relay.
   The PDF has a cover page, an executive summary (business need, a solutions
   table, and a "why these recommendations" list — richer if the Sales Agent
   passes `requirements_summary`), solutions grouped by category, and page
   numbers on every page. All dynamic text is HTML-escaped before rendering
   (in both the email HTML and the PDF) so a description containing
   `&`/`<`/`>` can't corrupt the markup.

All required environment variables are validated at startup (`config.py`) —
the app fails fast with a clear error listing anything missing from `.env`.

## Guardrails

The Sales Agent uses the OpenAI Agents SDK's `input_guardrails`/
`output_guardrails` (`guardrails.py`), on top of the trusted-domain link
filtering already built into the research and email tools:

- **`pii_input_guardrail`** (input, regex, no LLM call) — blocks the turn if
  the customer's message contains sensitive data we don't need (card numbers,
  SSNs, passwords, etc.), before it ever reaches the model.
- **`on_topic_guardrail`** (input, small classifier agent) — blocks prompt
  injection / off-topic hijack attempts ("ignore your instructions", "reveal
  your system prompt", unrelated tasks) while staying permissive on normal
  business conversation. Both input guardrails run *before* the agent starts
  generating (`run_in_parallel=False`), so a blocked turn shows a clean
  decline message instead of a partial answer.
- **`untrusted_link_guardrail`** (output, regex) — a backstop that scans the
  agent's own reply text for any URL not on the DT/Vonage allowlist. Because
  replies are streamed token-by-token, this runs after the text has already
  reached the UI, so it can only flag-and-correct (appends a warning), not
  prevent — the real prevention for links is the code-level filtering in
  `tools/research_tool.py` and `tools/email_tool.py`.

`app.py` catches `InputGuardrailTripwireTriggered` /
`OutputGuardrailTripwireTriggered` and responds with a friendly message
instead of crashing the chat; tripped guardrails are also logged to the
console with their details.

## Rate-limit fallback

`SQLiteSession` sends the *entire* growing conversation on every turn, and
`research_dt_solutions`'s web search adds real token volume on top — it's
easy to hit OpenAI's tokens-per-minute cap in a longer conversation. If
`GEMINI_API_KEY` is set in `.env` (get one from Google AI Studio), the Sales
Agent and its `on_topic_guardrail` classifier automatically retry via Gemini
(`gemini-3.1-flash-lite` by default, `GEMINI_MODEL_NAME` to override) when an
OpenAI call raises `openai.RateLimitError` — transparent to the customer,
logged to the console. Pattern verified against
`agents/2_openai/3_lab3.ipynb` / `agents/6_mcp/backend/traders.py`: Gemini's
OpenAI-compatible endpoint plugged in via `OpenAIChatCompletionsModel`
(`gemini_fallback.py`).

Scope: **not** the Researcher Agent (`research_dt_solutions`) — it depends on
OpenAI's hosted `WebSearchTool`, which has no Gemini equivalent in the Agents
SDK, so a rate limit during a research call isn't rescued by this. It only
retries when nothing has streamed back to the customer yet for that turn (the
common case — rate limits surface before any tokens stream); a failure that
happens mid-response, or any failure with no Gemini key configured, shows a
"having trouble connecting, try again" message instead of crashing the chat.
Without a Gemini key, the app behaves exactly as before (`gemini_sales_agent`
is `None`, no fallback attempted).

### Research vs. sharing: two different trust boundaries

`tools/fetch_tool.py`'s `fetch_page` is intentionally unrestricted in *what*
it can read (any http/https URL) — that's what lets the researcher actually
understand a customer's business in depth. It has a basic SSRF guard (blocks
non-http(s) schemes and hosts that resolve to private/loopback/link-local
addresses, e.g. `localhost`, `169.254.169.254`), but not full protection
against DNS-rebinding (the safety check and the actual request each resolve
the host independently) — an acceptable tradeoff here since the tool only
ever fetches URLs the researcher itself found via search, not raw user input.

What's actually shown to the customer is a separate, unrelated boundary,
enforced independently in `trusted_domains.py` (shared `sanitize_solutions()`
helper, used by research findings, the proposal email, and the brochure PDF)
+ `untrusted_link_guardrail` (chat replies) — a page being *readable* never
makes it *citable*.
