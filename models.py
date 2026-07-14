from pydantic import BaseModel, Field


class DTSolution(BaseModel):
    name: str = Field(description="The real Deutsche Telekom product/solution name")
    category: str = Field(
        description="e.g. Mobile & Fleet, Fixed Network & Broadband, IoT & M2M, Cloud & Security, Unified Comms"
    )
    description: str = Field(description="What the solution does, in plain business language")
    key_features: list[str] = Field(description="Notable features or capabilities")
    fit_rationale: str = Field(description="Why this solution fits the customer's stated requirements")
    source_url: str | None = Field(default=None, description="URL of the page this was found on")


class ResearchFindings(BaseModel):
    solutions: list[DTSolution] = Field(description="Matching Deutsche Telekom solutions found via web search")
    summary: str = Field(description="A 2-3 sentence summary of the research findings")


class ProposalContent(BaseModel):
    customer_name: str = Field(description="Name of the customer/company the proposal is for")
    company_snapshot: str = Field(description="Brief recap of the customer's business context")
    requirements_summary: str = Field(description="Summary of the requirements gathered during the conversation")
    recommended_solutions: list[DTSolution] = Field(description="The DT solutions being proposed")
    next_steps: str = Field(description="Suggested next steps / call to action")


class Lead(BaseModel):
    name: str = Field(description="Full name of the contact person")
    company: str = Field(description="The customer's company/organization name")
    email: str = Field(description="Primary contact email address — the main identifier for this lead")
    industry: str | None = Field(
        default=None, description="Industry or business sector, e.g. Logistics, Retail, Manufacturing"
    )
    lead_status: str | None = Field(
        default=None,
        description=(
            "Current stage of this lead, e.g. New, Contacted, Qualified, Proposal Sent, Won, Lost. "
            "Leave unset to let a new lead default to 'New' — only set this if you know the actual stage."
        ),
    )
    products_of_interest: str | None = Field(
        default=None,
        description="Comma-separated list of DT products/solution areas this lead has shown interest in so far",
    )
    notes: str | None = Field(
        default=None,
        description="Freeform notes about this lead's needs, conversation history, and context",
    )
    last_contact_date: str | None = Field(
        default=None,
        description="Date of the most recent contact with this lead, in YYYY-MM-DD format",
    )


class LeadUpdate(BaseModel):
    products_of_interest: str | None = Field(
        default=None,
        description=(
            "NEW product(s)/solution area(s) the customer has shown interest in during this "
            "conversation, e.g. 'Cloud Security'. This is MERGED into the lead's existing list "
            "(de-duplicated), never overwrites prior interests — pass only what's new, not the "
            "full accumulated list."
        ),
    )
    notes: str | None = Field(
        default=None,
        description=(
            "A NEW note to add about this interaction, e.g. a summary of what was discussed or a "
            "newly identified requirement. This is APPENDED as a new timestamped line to the "
            "lead's existing notes, never overwrites prior notes — pass only the new note text."
        ),
    )
    lead_status: str | None = Field(default=None, description="New lead status, if it has changed, e.g. Contacted, Proposal Sent")
    email: str | None = Field(default=None, description="Updated email address, if the customer gave a new/corrected one")
    industry: str | None = Field(default=None, description="Updated industry, if changed or newly learned")
    last_contact_date: str | None = Field(default=None, description="Date of this contact, in YYYY-MM-DD format — usually today")
