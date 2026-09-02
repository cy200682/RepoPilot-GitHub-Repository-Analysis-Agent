"""Provider-neutral contracts for repository memory and conversations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

MemoryType = Literal[
    "repository_summary",
    "entry_point",
    "core_module",
    "execution_flow",
    "module_relationship",
    "symbol_summary",
    "file_summary",
    "qa_answer",
    "negative",
]
MemoryStatus = Literal[
    "current",
    "reusable",
    "stale",
    "invalid",
    "superseded",
    "needs_review",
]
MemoryConfidence = Literal["confirmed", "inferred", "candidate"]


def memory_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> datetime:
    return datetime.now(UTC)


class RepositoryRecord(BaseModel):
    id: str
    normalized_url: str
    owner: str
    name: str
    default_branch: str | None = None
    created_at: datetime
    updated_at: datetime


class RevisionRecord(BaseModel):
    id: str
    repository_id: str
    commit_sha: str
    source_branch: str | None = None
    tree_fingerprint: str | None = None
    detected_stack: list[str] = Field(default_factory=list)
    created_at: datetime


class MemoryEvidence(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=100)
    observation_id: str
    source_kind: str
    resolution: str
    path: str
    start_line: int = Field(ge=1)
    start_col: int = Field(default=0, ge=0)
    end_line: int = Field(ge=1)
    end_col: int = Field(default=0, ge=0)
    content_hash: str | None = None
    verified: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> MemoryEvidence:
        if self.end_line < self.start_line:
            raise ValueError("Evidence end_line must be greater than or equal to start_line.")
        return self


class MemoryCandidate(BaseModel):
    memory_type: MemoryType
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=4_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    symbol_names: list[str] = Field(default_factory=list, max_length=30)
    paths: list[str] = Field(default_factory=list, max_length=30)
    confidence: MemoryConfidence = "inferred"
    evidence: list[MemoryEvidence] = Field(default_factory=list, max_length=20)
    coverage_notes: list[str] = Field(default_factory=list, max_length=20)


class MemoryEntry(MemoryCandidate):
    id: str
    repository_id: str
    revision_id: str
    source_run_id: str
    commit_sha: str
    status: MemoryStatus
    content_hash: str
    created_at: datetime
    updated_at: datetime
    match_kind: str | None = None
    match_score: float | None = None

    def tool_summary(self) -> dict[str, object]:
        return {
            "memory_id": self.id,
            "memory_type": self.memory_type,
            "title": self.title,
            "content": self.content,
            "tags": self.tags,
            "symbol_names": self.symbol_names,
            "paths": self.paths,
            "confidence": self.confidence,
            "status": self.status,
            "commit_sha": self.commit_sha,
            "evidence": [item.model_dump(mode="json") for item in self.evidence],
            "coverage_notes": self.coverage_notes,
            "match_kind": self.match_kind,
            "match_score": self.match_score,
        }


class ExplorationEpisode(BaseModel):
    id: str = Field(default_factory=lambda: memory_id("episode"))
    run_id: str
    revision_id: str
    goal: str
    explored_paths: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    confirmed_summary: str = ""
    rejected_hypotheses: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    coverage_notes: list[str] = Field(default_factory=list)
    stop_reason: str
    created_at: datetime = Field(default_factory=utc_now)


class ConversationRecord(BaseModel):
    id: str
    repository_id: str
    revision_id: str
    title: str
    summary: str
    summarized_through_sequence: int
    created_at: datetime
    updated_at: datetime


class MessageRecord(BaseModel):
    id: str
    conversation_id: str
    sequence: int
    role: Literal["user", "assistant", "system_event"]
    content: str
    answer_status: str | None = None
    source_run_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    token_usage: dict[str, int | bool] = Field(default_factory=dict)
    created_at: datetime


class MemoryStats(BaseModel):
    repositories: int = 0
    revisions: int = 0
    runs: int = 0
    memories: int = 0
    conversations: int = 0
    messages: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    fts_enabled: bool = False
