from dataclasses import dataclass

from models import ProposalContent, ResearchFindings


@dataclass
class SalesContext:
    customer_email: str
    customer_name: str
    customer_company: str

    # Scratch space a tool call leaves behind for the sales agent's own
    # on_tool_end hook (see agents_def/sales_agent.py) to act on — e.g. to
    # decide what CRM bookkeeping a completed tool call warrants. Tools set
    # these; only the hook reads and acts on them.
    last_research_findings: ResearchFindings | None = None
    last_sent_proposal: ProposalContent | None = None
    last_sent_proposal_recipient: str | None = None
