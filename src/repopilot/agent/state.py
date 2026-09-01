"""In-memory observations, trace, and run state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from repopilot.agent.actions import AgentAnalysisResult, AgentDecision


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class EvidenceLocation(BaseModel):
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class Observation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("obs"))
    step_id: str
    tool_name: str
    status: Literal["success", "error"]
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    evidence_locations: list[EvidenceLocation] = Field(default_factory=list)
    truncated: bool = False
    truncation_notes: list[str] = Field(default_factory=list)
    duration_ms: int = Field(default=0, ge=0)


class TraceStep(BaseModel):
    step_id: str
    rationale: str
    decision: AgentDecision | None = None
    observation_id: str | None = None
    observation: Observation | None = None
    error: str | None = None


class AgentTrace(BaseModel):
    run_id: str
    repository_url: str
    commit_sha: str
    goal: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    final_status: str | None = None
    llm_request_count: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    token_usage_estimated: bool = False
    steps: list[TraceStep] = Field(default_factory=list)


class AgentState(BaseModel):
    run_id: str = Field(default_factory=lambda: new_id("run"))
    goal: str
    repository_url: str
    commit_sha: str
    bootstrap_summary: str
    status: Literal["running", "completed", "budget_exhausted", "failed"] = "running"
    iteration_count: int = 0
    tool_call_count: int = 0
    consecutive_error_count: int = 0
    visited_files: set[str] = Field(default_factory=set)
    searched_queries: list[str] = Field(default_factory=list)
    total_read_chars: int = 0
    total_search_results: int = 0
    ast_parsed_files: set[str] = Field(default_factory=set)
    ast_cache_hits: int = 0
    ast_node_count: int = 0
    repository_map_node_count: int = 0
    repository_map_edge_count: int = 0
    ast_parse_errors: int = 0
    reference_query_count: int = 0
    relationship_query_count: int = 0
    llm_request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    token_usage_estimated: bool = False
    observations: list[Observation] = Field(default_factory=list)
    action_counts: dict[str, int] = Field(default_factory=dict)
    final_analysis: AgentAnalysisResult | None = None
