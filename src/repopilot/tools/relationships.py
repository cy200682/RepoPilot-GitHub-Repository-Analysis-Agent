"""Query the currently explored incremental Repository Map."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from repopilot.agent.state import Observation
from repopilot.config import Settings
from repopilot.tools.ast_helpers import (
    evidence_from_spans,
    require_repository_map,
    resolution_counts,
)
from repopilot.tools.base import ToolContext

RelationshipInput = Literal["defines", "imports", "inherits", "calls", "references"]


class GetRelationshipsInput(BaseModel):
    symbol_id: str | None = None
    path: str | None = None
    direction: Literal["incoming", "outgoing", "both"] = "both"
    types: list[RelationshipInput] = Field(default_factory=list)
    max_depth: int = Field(default=1, ge=1, le=2)
    max_results: int | None = Field(default=None, ge=1, le=2_000)

    @model_validator(mode="after")
    def require_scope(self) -> GetRelationshipsInput:
        if not self.symbol_id and not self.path:
            raise ValueError("symbol_id or path is required.")
        return self


class GetRelationshipsTool:
    name = "get_relationships"
    description = "Query relationships already present in the incremental Repository Map."
    input_model: type[BaseModel] = GetRelationshipsInput

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(self, arguments: BaseModel, context: ToolContext, step_id: str) -> Observation:
        args = GetRelationshipsInput.model_validate(arguments)
        repository_map = require_repository_map(context)
        limit = min(
            args.max_results or self.settings.ast_max_tool_results,
            self.settings.ast_max_tool_results,
        )
        records = repository_map.query(
            symbol_id=args.symbol_id,
            path=args.path,
            direction=args.direction,
            relationship_types=set(args.types) or None,
            max_depth=args.max_depth,
            max_results=limit + 1,
        )
        selected = records[:limit]
        snapshot = repository_map.snapshot()
        truncated = len(records) > len(selected) or snapshot.truncated
        notes = list(snapshot.truncation_notes)
        if len(records) > len(selected):
            notes.append(f"Relationship results limited to {limit}.")
        return Observation(
            step_id=step_id,
            tool_name=self.name,
            status="success",
            summary=(
                f"Returned {len(selected)} relationships from a map covering "
                f"{len(snapshot.indexed_files)} files."
            ),
            data={
                "relationships": [item.model_dump(mode="json") for item in selected],
                "parse_status": "not_applicable",
                "indexed_files": snapshot.indexed_files,
                "coverage_notes": [
                    "This query covers only files already parsed through Agent tool actions."
                ],
                "map_nodes": len(snapshot.nodes),
                "map_edges": len(snapshot.edges),
                "max_depth": args.max_depth,
                "resolution_counts": resolution_counts(selected),
            },
            evidence_locations=evidence_from_spans([item.span for item in selected]),
            truncated=truncated,
            truncation_notes=notes,
        )
