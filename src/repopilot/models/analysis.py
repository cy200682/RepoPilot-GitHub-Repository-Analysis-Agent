"""LLM request and validated repository analysis contracts."""

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    """A path-grounded claim produced from supplied repository context."""

    claim: str
    path: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    verified: bool = False


class AnalysisRequest(BaseModel):
    """Provider-neutral request sent to an LLM adapter."""

    repository_name: str
    commit_sha: str
    context: str
    truncated: bool = False
    truncation_notes: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Structured Phase 1 result before Markdown rendering."""

    project_summary: str
    technology_stack: list[str] = Field(default_factory=list)
    directory_overview: list[str] = Field(default_factory=list)
    entrypoint_candidates: list[str] = Field(default_factory=list)
    core_module_candidates: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    recommended_reading_order: list[str] = Field(default_factory=list)
