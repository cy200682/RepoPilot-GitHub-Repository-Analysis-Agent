"""Agent tool for bounded single-file Python structure inspection."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from repopilot.agent.state import Observation
from repopilot.analysis.models import SourceSpan
from repopilot.config import Settings
from repopilot.tools.ast_helpers import (
    ast_file_limit,
    ast_usage,
    evidence_from_spans,
    require_code_index,
    resolution_counts,
)
from repopilot.tools.base import ToolContext

StructureKind = Literal["symbols", "imports", "inheritances", "calls", "references"]


def _default_structures() -> list[StructureKind]:
    return ["symbols", "imports"]


class InspectPythonInput(BaseModel):
    path: str
    include: list[StructureKind] = Field(default_factory=_default_structures)
    symbol: str | None = None
    max_results: int | None = Field(default=None, ge=1, le=2_000)


class InspectPythonTool:
    name = "inspect_python"
    description = (
        "Parse one requested Python file and return bounded AST symbols and static relationships."
    )
    input_model: type[BaseModel] = InspectPythonInput

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(self, arguments: BaseModel, context: ToolContext, step_id: str) -> Observation:
        args = InspectPythonInput.model_validate(arguments)
        index = require_code_index(context)
        if args.path not in index.parsed_files and ast_file_limit(context, 1) == 0:
            return Observation(
                step_id=step_id,
                tool_name=self.name,
                status="success",
                summary="AST file budget exhausted before parsing the requested file.",
                data={
                    "path": args.path,
                    "parse_status": "skipped",
                    "indexed_files": sorted(index.parsed_files),
                    "coverage_notes": ["The requested file is not present in the lazy index."],
                    "resolution_counts": {},
                    "map_updates": {"nodes": 0, "edges": 0},
                    "ast_usage": ast_usage(index, index.parsed_files, index.node_count),
                },
                truncated=True,
                truncation_notes=["Agent AST file budget exhausted."],
            )
        if args.path not in index.module_index.python_paths:
            raise ValueError("inspect_python path must be a scanned Python file.")
        before_files = index.parsed_files
        before_nodes = index.node_count
        analysis, cached = index.analyze(args.path)
        limit = min(
            args.max_results or self.settings.ast_max_tool_results,
            self.settings.ast_max_tool_results,
        )
        data: dict[str, object] = {
            "path": analysis.path,
            "module_name": analysis.module_name,
            "parse_status": analysis.parse_status,
            "syntax_error": analysis.syntax_error,
            "cached": cached,
            "indexed_files": sorted(index.parsed_files),
        }
        spans: list[SourceSpan] = []
        returned_records: list[object] = []
        total_results = 0
        for kind in args.include:
            records = list(getattr(analysis, kind))
            if args.symbol:
                records = [
                    item
                    for item in records
                    if args.symbol
                    in {
                        getattr(item, "name", None),
                        getattr(item, "qualified_name", None),
                        getattr(item, "symbol_id", None),
                        getattr(item, "caller_symbol_id", None),
                    }
                ]
            remaining = max(limit - total_results, 0)
            selected = records[:remaining]
            data[kind] = [item.model_dump(mode="json") for item in selected]
            returned_records.extend(selected)
            spans.extend(item.span for item in selected)
            total_results += len(selected)
        usage = ast_usage(index, before_files, before_nodes)
        data["ast_usage"] = usage
        data["resolution_counts"] = resolution_counts(returned_records)
        data["map_updates"] = {
            "nodes": usage["map_nodes"],
            "edges": usage["map_edges"],
        }
        data["coverage_notes"] = [
            f"Repository Map currently covers {len(index.parsed_files)} parsed Python files."
        ]
        total_available = sum(len(getattr(analysis, kind)) for kind in args.include)
        truncated = analysis.truncated or total_available > total_results
        notes = list(analysis.truncation_notes)
        if total_available > total_results:
            notes.append(f"Tool output limited to {limit} records.")
        return Observation(
            step_id=step_id,
            tool_name=self.name,
            status="success",
            summary=(
                f"Inspected {analysis.path}: {len(analysis.symbols)} symbols, "
                f"{len(analysis.imports)} imports, {len(analysis.calls)} calls; "
                f"status={analysis.parse_status}."
            ),
            data=data,
            evidence_locations=evidence_from_spans(spans),
            truncated=truncated,
            truncation_notes=notes,
        )
