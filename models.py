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
