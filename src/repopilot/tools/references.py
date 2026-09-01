"""AST-validated static reference lookup."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from repopilot.agent.state import Observation
from repopilot.config import Settings
from repopilot.tools.ast_helpers import (
    ast_file_limit,
    ast_usage,
    evidence_from_spans,
    require_code_index,
    resolution_counts,
)
from repopilot.tools.base import ToolContext
from repopilot.tools.search import SearchCodeInput, SearchCodeTool

ReferenceKindInput = Literal["name", "attribute", "import", "call", "decorator", "base"]


class FindReferencesInput(BaseModel):
    symbol_id: str | None = None
    name: str | None = None
    path: str = "."
    kinds: list[ReferenceKindInput] = Field(default_factory=list)
    max_results: int | None = Field(default=None, ge=1, le=2_000)
    include_candidates: bool = True

    @model_validator(mode="after")
    def require_target(self) -> FindReferencesInput:
        if not self.symbol_id and not self.name:
            raise ValueError("symbol_id or name is required.")
        return self


class FindReferencesTool:
    name = "find_references"
    description = "Find AST-validated static references to a Python symbol or name."
    input_model: type[BaseModel] = FindReferencesInput

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.search = SearchCodeTool(settings)

    def execute(self, arguments: BaseModel, context: ToolContext, step_id: str) -> Observation:
        args = FindReferencesInput.model_validate(arguments)
        index = require_code_index(context)
        name = args.name or (args.symbol_id or "").rsplit(".", 1)[-1].rsplit(":", 1)[-1]
        search = self.search.execute(
            SearchCodeInput(
                query=name,
                path=args.path,
                file_glob="*.py",
                case_sensitive=True,
                max_results=self.settings.tool_max_search_results,
                context_lines=0,
            ),
            context,
            step_id,
        )
        candidate_paths = list(
            dict.fromkeys(str(item["path"]) for item in search.data.get("matches", []))
        )[: self.settings.reference_max_candidate_files]
        before_files = index.parsed_files
        before_nodes = index.node_count
        parse_limit = ast_file_limit(context, self.settings.ast_max_files_per_tool)
        uncached = [path for path in candidate_paths if path not in index.parsed_files]
        allowed_uncached = set(uncached[:parse_limit])
        paths_to_analyze = [
            path
            for path in candidate_paths
            if path in index.parsed_files or path in allowed_uncached
        ]
        for path in paths_to_analyze:
            index.analyze(path)
        limit = min(
            args.max_results or self.settings.ast_max_tool_results,
            self.settings.ast_max_tool_results,
        )
        records = []
        for analysis in index.analyses.values():
            for item in analysis.references:
                if item.symbol_name != name:
                    continue
                if args.kinds and item.reference_kind not in args.kinds:
                    continue
                if (
                    args.symbol_id
                    and item.resolved_symbol_id != args.symbol_id
                    and (not args.include_candidates or item.resolution == "resolved")
                ):
                    continue
                records.append(item)
        records.sort(key=lambda item: (item.span.path, item.span.start_line, item.span.start_col))
        selected = records[:limit]
        usage = ast_usage(index, before_files, before_nodes)
        statuses = {index.analyses[path].parse_status for path in paths_to_analyze}
        parse_status = (
            "syntax_error"
            if "syntax_error" in statuses
            else "truncated"
            if "truncated" in statuses
            else "parsed"
        )
        truncated = len(records) > len(selected) or len(paths_to_analyze) < len(candidate_paths)
        notes = []
        if len(records) > len(selected):
            notes.append(f"Reference results limited to {limit}.")
        if len(paths_to_analyze) < len(candidate_paths):
            notes.append(f"Candidate parsing limited to {len(paths_to_analyze)} files by budget.")
        return Observation(
            step_id=step_id,
            tool_name=self.name,
            status="success",
            summary=f"Found {len(records)} AST references for {name!r}; returned {len(selected)}.",
            data={
                "target": {"symbol_id": args.symbol_id, "name": name},
                "references": [item.model_dump(mode="json") for item in selected],
                "searched_files": candidate_paths,
                "analyzed_files": paths_to_analyze,
                "parsed_files": sorted(index.parsed_files - before_files),
                "parse_status": parse_status,
                "indexed_files": sorted(index.parsed_files),
                "resolution_counts": resolution_counts(selected),
                "coverage_notes": [
                    "Only text-matched candidate files and previously indexed files were inspected."
                ],
                "ast_usage": usage,
            },
            evidence_locations=evidence_from_spans([item.span for item in selected]),
            truncated=truncated,
            truncation_notes=notes,
        )
