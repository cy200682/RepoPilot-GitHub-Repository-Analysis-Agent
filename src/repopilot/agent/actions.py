"""Provider-neutral Agent decisions and final analysis contracts."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class AgentEvidence(BaseModel):
    evidence_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", min_length=1, max_length=100)
    claim: str = Field(min_length=1, max_length=2_000)
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    observation_id: str
    confidence: Literal["confirmed", "inferred", "candidate"] = "confirmed"
    source_kind: Literal[
        "read",
        "search",
        "ast_symbol",
        "ast_import",
        "ast_inheritance",
        "ast_call",
        "ast_reference",
        "map_query",
    ] = "read"
    resolution: Literal[
        "resolved",
        "inferred",
        "candidate",
        "ambiguous",
        "external",
        "unresolved",
        "not_applicable",
    ] = "not_applicable"
    verified: bool = False

    @model_validator(mode="after")
    def validate_line_range(self) -> "AgentEvidence":
        if self.end_line < self.start_line:
            raise ValueError("Evidence end_line must be greater than or equal to start_line.")
        return self


class AgentFinding(BaseModel):
    """One report conclusion with explicit links to supporting Evidence."""

    claim: str = Field(min_length=1, max_length=2_000)
    confidence: Literal["confirmed", "inferred", "candidate"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class AgentAnalysisResult(BaseModel):
    project_summary: str
    technology_stack: list[str] = Field(default_factory=list)
    directory_overview: list[str] = Field(default_factory=list)
    entrypoints: list[AgentFinding] = Field(default_factory=list)
    core_modules: list[AgentFinding] = Field(default_factory=list)
    execution_flows: list[AgentFinding] = Field(default_factory=list)
    module_relationships: list[AgentFinding] = Field(default_factory=list)
    key_symbols: list[str] = Field(default_factory=list)
    important_designs: list[str] = Field(default_factory=list)
    engineering_risks: list[str] = Field(default_factory=list)
    evidence: list[AgentEvidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    recommended_reading_order: list[str] = Field(default_factory=list)


class ToolAction(BaseModel):
    type: Literal["tool"] = "tool"
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class FinishAction(BaseModel):
    type: Literal["finish"] = "finish"
    analysis: AgentAnalysisResult


AgentAction = Annotated[ToolAction | FinishAction, Field(discriminator="type")]


class AgentDecision(BaseModel):
    rationale: str = Field(min_length=1, max_length=500)
    action: AgentAction
