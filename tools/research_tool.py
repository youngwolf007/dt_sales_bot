from agents import RunContextWrapper, Runner, SQLiteSession, function_tool

from agents_def.researcher_agent import researcher_agent
from context import SalesContext
from models import ResearchFindings
from trusted_domains import sanitize_solutions

SESSIONS_DB = "dt_sales_bot_sessions.db"


def _researcher_session(customer_email: str) -> SQLiteSession:
    return SQLiteSession(f"research::{customer_email}", SESSIONS_DB)


def _strip_untrusted_links(findings: ResearchFindings) -> ResearchFindings:
    """Defense in depth: null out any source_url that isn't a genuine DT/Vonage
    domain, in case the researcher didn't follow its sourcing instructions."""
    return findings.model_copy(update={"solutions": sanitize_solutions(findings.solutions)})


def _format_findings(findings: ResearchFindings) -> str:
    lines = [findings.summary, ""]
    for solution in findings.solutions:
        lines.append(f"- {solution.name} ({solution.category}): {solution.description}")
        if solution.key_features:
            lines.append(f"  Features: {', '.join(solution.key_features)}")
        lines.append(f"  Fit: {solution.fit_rationale}")
        if solution.source_url:
            lines.append(f"  Source: {solution.source_url}")
    return "\n".join(lines)


@function_tool
async def research_dt_solutions(ctx: RunContextWrapper[SalesContext], need: str) -> str:
    """
    Search the live web for real, current Deutsche Telekom (and T-Systems)
    B2B products/solutions matching a described business need. Call this
    whenever you need facts about what DT actually offers — never guess.

    This researcher remembers earlier findings for this same customer, so
    follow-up calls can build on prior research instead of starting cold.

    Args:
        need: A clear, specific description of the customer's business need.
    """
    session = _researcher_session(ctx.context.customer_email)
    try:
        result = await Runner.run(researcher_agent, need, session=session)
    except Exception as exc:  # noqa: BLE001 - surface research failures to the sales agent
        return f"Research failed: {exc}. Try again or narrow the request."

    findings = _strip_untrusted_links(result.final_output)
    # Recorded here purely as data for the sales agent's own on_tool_end hook
    # (see agents_def/sales_agent.py) to act on — this tool's job is research,
    # not deciding what goes into the CRM.
    ctx.context.last_research_findings = findings
    return _format_findings(findings)
