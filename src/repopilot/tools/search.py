"""Bounded literal or regular-expression repository search."""

from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath
from time import perf_counter

from pydantic import BaseModel, Field

from repopilot.agent.state import EvidenceLocation, Observation
from repopilot.config import Settings
from repopilot.exceptions import RepositoryReadError
from repopilot.tools.base import ToolContext


class SearchCodeInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    path: str = "."
    is_regex: bool = False
    file_glob: str | None = Field(default=None, max_length=200)
    case_sensitive: bool = False
    max_results: int | None = Field(default=None, ge=1, le=500)
    context_lines: int = Field(default=2, ge=0, le=10)


class SearchCodeTool:
    name = "search_code"
    description = "Search bounded repository text and return path, line, and excerpts."
    input_model: type[BaseModel] = SearchCodeInput

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(
        self,
        arguments: BaseModel,
        context: ToolContext,
        step_id: str,
    ) -> Observation:
        args = SearchCodeInput.model_validate(arguments)
        scope = self._safe_scope(args.path)
        limit = min(
            args.max_results or self.settings.tool_max_search_results,
            self.settings.tool_max_search_results,
        )
        flags = 0 if args.case_sensitive else re.IGNORECASE
        expression = args.query if args.is_regex else re.escape(args.query)
        try:
            pattern = re.compile(expression, flags)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc

        started = perf_counter()
        matches: list[dict[str, object]] = []
        evidence: list[EvidenceLocation] = []
        total_matches = 0
        for file in context.snapshot.files:
            if not file.is_text or not self._in_scope(file.relative_path, scope):
                continue
            if args.file_glob and not fnmatch.fnmatch(file.relative_path, args.file_glob):
                continue
            if perf_counter() - started > self.settings.tool_search_timeout_seconds:
                break
            try:
                result = context.reader.read_file(context.root_path, file.relative_path)
            except RepositoryReadError:
                continue
            lines = result.content.splitlines()
            for index, line in enumerate(lines):
                found = pattern.search(line)
                if not found:
                    continue
                total_matches += 1
                if len(matches) >= limit:
                    continue
                start = max(0, index - args.context_lines)
                end = min(len(lines), index + args.context_lines + 1)
                excerpt = "\n".join(
                    f"{line_number + 1}: {lines[line_number]}" for line_number in range(start, end)
                )
                matches.append(
                    {
                        "path": file.relative_path,
                        "line": index + 1,
                        "match_text": found.group(0),
                        "excerpt": excerpt,
                    }
                )
                evidence.append(
                    EvidenceLocation(
                        path=file.relative_path,
                        start_line=index + 1,
                        end_line=index + 1,
                    )
                )

        truncated = total_matches > len(matches)
        return Observation(
            step_id=step_id,
            tool_name=self.name,
            status="success",
            summary=f"Found {total_matches} matches for {args.query!r}; returned {len(matches)}.",
            data={
                "query": args.query,
                "matches": matches,
                "total_matches": total_matches,
                "returned_count": len(matches),
            },
            evidence_locations=evidence,
            truncated=truncated,
            truncation_notes=[f"Search results limited to {limit} matches."] if truncated else [],
        )

    @staticmethod
    def _safe_scope(path: str) -> str:
        normalized = PurePosixPath(path.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("Search path must stay inside the repository root.")
        return normalized.as_posix()

    @staticmethod
    def _in_scope(path: str, scope: str) -> bool:
        return scope == "." or path == scope or path.startswith(f"{scope}/")
