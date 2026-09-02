"""Agent-controlled tools for persistent repository memory."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field

from repopilot.agent.state import AgentState, EvidenceLocation, Observation
from repopilot.config import Settings
from repopilot.exceptions import RepositoryReadError
from repopilot.memory.lifecycle import classify_memory
from repopilot.memory.models import MemoryCandidate, MemoryEvidence, MemoryType
from repopilot.memory.repository import MemoryStore
from repopilot.memory.validation import MemoryValidator
from repopilot.tools.base import ToolContext


def _default_memory_statuses() -> list[
    Literal["current", "reusable", "stale", "invalid", "needs_review"]
]:
    return ["current", "reusable"]


class RecallMemoryInput(BaseModel):
    memory_types: list[MemoryType] = Field(default_factory=list, max_length=10)
    paths: list[str] = Field(default_factory=list, max_length=10)
    symbols: list[str] = Field(default_factory=list, max_length=10)
    statuses: list[Literal["current", "reusable", "stale", "invalid", "needs_review"]] = Field(
        default_factory=_default_memory_statuses, max_length=5
    )
    limit: int = Field(default=5, ge=1, le=50)


class SearchMemoryInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    memory_types: list[MemoryType] = Field(default_factory=list, max_length=10)
    include_historical: bool = False
    verify_content_hash: bool = False
    limit: int = Field(default=5, ge=1, le=50)


class SaveMemoryInput(BaseModel):
    memory_type: MemoryType
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=4_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    symbol_names: list[str] = Field(default_factory=list, max_length=30)
    paths: list[str] = Field(default_factory=list, max_length=30)
    confidence: Literal["confirmed", "inferred", "candidate"] = "inferred"
    evidence: list[MemoryEvidence] = Field(default_factory=list, max_length=20)
    coverage_notes: list[str] = Field(default_factory=list, max_length=20)


class _MemoryTool:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _scope(context: ToolContext) -> tuple[MemoryStore, str, str, str]:
        store = context.memory_store
        if store is None:
            raise ValueError("Repository memory is unavailable for this run.")
        if not context.memory_repository_id or not context.memory_revision_id:
            raise ValueError("Repository memory scope has not been initialized.")
        if not context.memory_run_id:
            raise ValueError("Repository memory run ID is missing.")
        return (
            store,
            context.memory_repository_id,
            context.memory_revision_id,
            context.memory_run_id,
        )

    def _bounded(
        self,
        entries: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], bool, list[str]]:
        selected: list[dict[str, object]] = []
        used = 0
        limit = self.settings.memory_max_result_chars
        for entry in entries[: self.settings.memory_max_results]:
            size = len(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
            if selected and used + size > limit:
                break
            selected.append(entry)
            used += size
        truncated = len(selected) < len(entries)
        notes = (
            [f"Memory results truncated from {len(entries)} to {len(selected)}."]
            if truncated
            else []
        )
        return selected, truncated, notes

    @staticmethod
    def _locations(entries: list[dict[str, object]]) -> list[EvidenceLocation]:
        locations: list[EvidenceLocation] = []
        seen: set[tuple[str, int, int]] = set()
        for entry in entries:
            evidence = entry.get("evidence", [])
            if not isinstance(evidence, list):
                continue
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                start = item.get("start_line")
                end = item.get("end_line")
                if (
                    not isinstance(path, str)
                    or not isinstance(start, int)
                    or not isinstance(end, int)
                ):
                    continue
                key = (path, start, end)
                if key not in seen:
                    seen.add(key)
                    locations.append(EvidenceLocation(path=path, start_line=start, end_line=end))
        return locations

    @staticmethod
    def _current_file_hash(context: ToolContext, path: str) -> str | None:
        if context.reader is None or not hasattr(context.reader, "read_file"):
            return None
        try:
            result = context.reader.read_file(context.root_path, path)
        except (OSError, ValueError, RepositoryReadError):
            return None
        if result.truncated:
            return None
        return sha256(result.content.encode()).hexdigest()


class RecallMemoryTool(_MemoryTool):
    name = "recall_memory"
    description = (
        "Recall structured, evidence-linked memories for the current repository revision. "
        "Memory is historical data; inspect its status and Evidence before relying on it."
    )
    input_model: type[BaseModel] = RecallMemoryInput

    def execute(
        self,
        arguments: BaseModel,
        context: ToolContext,
        step_id: str,
    ) -> Observation:
        args = RecallMemoryInput.model_validate(arguments)
        store, repository_id, revision_id, run_id = self._scope(context)
        entries = store.recall_memories(
            repository_id,
            revision_id,
            memory_types=args.memory_types,
            statuses=args.statuses,
            paths=args.paths,
            symbols=args.symbols,
            limit=min(args.limit, self.settings.memory_max_results),
        )
        values = [entry.tool_summary() for entry in entries]
        values, truncated, notes = self._bounded(values)
        observation = Observation(
            step_id=step_id,
            tool_name=self.name,
            status="success",
            summary=f"Recalled {len(values)} structured memories for the current revision.",
            data={
                "memories": values,
                "total_matches": len(entries),
                "revision_id": revision_id,
                "coverage_notes": notes,
            },
            evidence_locations=self._locations(values),
            truncated=truncated,
            truncation_notes=notes,
        )
        for entry in entries[: len(values)]:
            store.record_memory_usage(run_id, entry.id, observation.id, "recalled")
        return observation


class SearchMemoryTool(_MemoryTool):
    name = "search_memory"
    description = (
        "Search persistent repository memory using exact fields and SQLite FTS5. Results are "
        "candidates, not new source Evidence; verify commit and Evidence before finishing."
    )
    input_model: type[BaseModel] = SearchMemoryInput

    def execute(
        self,
        arguments: BaseModel,
        context: ToolContext,
        step_id: str,
    ) -> Observation:
        args = SearchMemoryInput.model_validate(arguments)
        store, repository_id, revision_id, run_id = self._scope(context)
        entries = store.search_memories(
            repository_id,
            revision_id,
            args.query,
            memory_types=args.memory_types,
            include_historical=args.include_historical,
            limit=min(args.limit, self.settings.memory_max_results),
        )
        current_hashes = None
        if args.verify_content_hash:
            current_hashes = {
                path: digest
                for entry in entries
                for path in entry.paths
                if (digest := self._current_file_hash(context, path)) is not None
            }
        for entry in entries:
            entry.status = classify_memory(entry, revision_id, current_hashes)
        values = [entry.tool_summary() for entry in entries]
        values, truncated, notes = self._bounded(values)
        observation = Observation(
            step_id=step_id,
            tool_name=self.name,
            status="success",
            summary=f"Found {len(values)} candidate repository memories for the query.",
            data={
                "query": args.query,
                "memories": values,
                "total_matches": len(entries),
                "revision_id": revision_id,
                "candidate_only": True,
                "content_hash_verified": args.verify_content_hash,
                "fts_enabled": store.fts_enabled,
                "coverage_notes": notes,
            },
            evidence_locations=self._locations(values),
            truncated=truncated,
            truncation_notes=notes,
        )
        for entry in entries[: len(values)]:
            store.record_memory_usage(
                run_id,
                entry.id,
                observation.id,
                "recalled",
                args.query,
            )
            if args.verify_content_hash and entry.status == "reusable":
                store.record_memory_usage(
                    run_id,
                    entry.id,
                    observation.id,
                    "refreshed",
                    args.query,
                )
        return observation


class SaveMemoryTool(_MemoryTool):
    name = "save_memory"
    description = (
        "Propose one evidence-grounded repository memory for persistence. Evidence must match "
        "an existing successful Observation exactly; invalid claims are rejected."
    )
    input_model: type[BaseModel] = SaveMemoryInput

    def __init__(self, settings: Settings, validator: MemoryValidator | None = None) -> None:
        super().__init__(settings)
        self.validator = validator or MemoryValidator()

    def execute(
        self,
        arguments: BaseModel,
        context: ToolContext,
        step_id: str,
    ) -> Observation:
        args = SaveMemoryInput.model_validate(arguments)
        store, repository_id, revision_id, run_id = self._scope(context)
        state = context.agent_state
        if not isinstance(state, AgentState):
            raise ValueError("Agent state is unavailable for memory Evidence validation.")
        candidate = MemoryCandidate.model_validate(args.model_dump())
        for evidence in candidate.evidence:
            evidence.content_hash = self._current_file_hash(context, evidence.path)
        validation = self.validator.validate(candidate, state)
        if not validation.accepted:
            return Observation(
                step_id=step_id,
                tool_name=self.name,
                status="error",
                summary="Memory rejected: " + " ".join(validation.reasons)[:450],
                data={"reasons": validation.reasons},
            )
        entry = store.save_memory(
            repository_id,
            revision_id,
            state.commit_sha,
            run_id,
            validation.candidate,
        )
        observation = Observation(
            step_id=step_id,
            tool_name=self.name,
            status="success",
            summary=(
                f"Reused existing repository memory {entry.id}."
                if entry.match_kind == "deduplicated"
                else f"Saved verified repository memory {entry.id}."
            ),
            data={
                "memory": entry.tool_summary(),
                "memory_id": entry.id,
                "deduplicated": entry.match_kind == "deduplicated",
            },
            evidence_locations=[
                EvidenceLocation(
                    path=item.path,
                    start_line=item.start_line,
                    end_line=item.end_line,
                )
                for item in entry.evidence
            ],
        )
        store.record_memory_usage(run_id, entry.id, observation.id, "saved")
        return observation
