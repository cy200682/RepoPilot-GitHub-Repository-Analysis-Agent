"""AST-enhanced Python symbol lookup with an explicit text fallback."""

import re

from pydantic import BaseModel, Field

from repopilot.agent.state import EvidenceLocation, Observation
from repopilot.analysis.code_index import CodeIndex
from repopilot.config import Settings
from repopilot.tools.ast_helpers import (
    ast_file_limit,
    ast_usage,
    evidence_from_spans,
)
from repopilot.tools.base import ToolContext
from repopilot.tools.search import SearchCodeInput, SearchCodeTool


class FindSymbolInput(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    kind: str = Field(default="any", pattern=r"^(class|function|method|any)$")
    path: str = "."
    language: str | None = "Python"
    max_results: int | None = Field(default=None, ge=1, le=100)


class FindSymbolTool:
    name = "find_symbol"
    description = (
        "Find Python symbol definitions using AST, with candidate fallback on parse errors."
    )
    input_model: type[BaseModel] = FindSymbolInput

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.search_tool = SearchCodeTool(settings)

    def execute(
        self,
        arguments: BaseModel,
        context: ToolContext,
        step_id: str,
    ) -> Observation:
        args = FindSymbolInput.model_validate(arguments)
        if args.language and args.language.lower() != "python":
            raise ValueError("Phase 3 find_symbol only supports Python AST or text candidates.")
        expression = self._expression(args.name, args.kind)
        search = self.search_tool.execute(
            SearchCodeInput(
                query=expression,
                path=args.path,
                is_regex=True,
                file_glob="*.py",
                case_sensitive=True,
                max_results=args.max_results,
                context_lines=0,
            ),
            context,
            step_id,
        )
        index = context.code_index if isinstance(context.code_index, CodeIndex) else None
        if index is None:
            return self._text_fallback(args, search, step_id)
        before_files = index.parsed_files
        before_nodes = index.node_count
        all_candidate_paths = list(
            dict.fromkeys(str(item["path"]) for item in search.data.get("matches", []))
        )
        parse_limit = ast_file_limit(context, self.settings.ast_max_files_per_tool)
        uncached = [path for path in all_candidate_paths if path not in index.parsed_files]
        allowed_uncached = set(uncached[:parse_limit])
        candidate_paths = [
            path
            for path in all_candidate_paths
            if path in index.parsed_files or path in allowed_uncached
        ]
        fallback_paths = set(all_candidate_paths) - set(candidate_paths)
        for path in candidate_paths:
            analysis, _ = index.analyze(path)
            if analysis.parse_status == "syntax_error":
                fallback_paths.add(path)
        symbols = []
        for path in candidate_paths:
            analysis = index.analyses[path]
            for symbol in analysis.symbols:
                if symbol.name != args.name or not self._kind_matches(args.kind, symbol.kind):
                    continue
                symbols.append(symbol)
        symbols.sort(key=lambda item: (item.path, item.span.start_line, item.qualified_name))
        limit = min(args.max_results or 100, self.settings.ast_max_tool_results)
        selected = symbols[:limit]
        candidates = [
            {
                **item.model_dump(mode="json"),
                "line": item.span.start_line,
                "signature_excerpt": item.qualified_name,
                "confidence": "confirmed",
                "source": "ast",
                "resolution": "exact",
            }
            for item in selected
        ]
        for match in search.data.get("matches", []):
            if str(match["path"]) not in fallback_paths or len(candidates) >= limit:
                continue
            candidates.append(
                {
                    "path": match["path"],
                    "line": match["line"],
                    "kind": "candidate",
                    "signature_excerpt": match["excerpt"],
                    "confidence": "candidate",
                    "source": "text_fallback",
                    "resolution": "candidate",
                }
            )
        usage = ast_usage(index, before_files, before_nodes)
        spans = [item.span for item in selected]
        fallback_evidence = [
            EvidenceLocation(
                path=str(item["path"]), start_line=int(item["line"]), end_line=int(item["line"])
            )
            for item in search.data.get("matches", [])
            if str(item["path"]) in fallback_paths
        ]
        return Observation(
            step_id=step_id,
            tool_name=self.name,
            status="success",
            summary=(
                f"Found {len(candidates)} definitions for symbol {args.name}; "
                f"AST exact={len(selected)}."
            ),
            data={
                "symbol": args.name,
                "candidates": candidates,
                "resolution": "exact"
                if len(selected) == 1
                else "ambiguous"
                if selected
                else "candidate",
                "ast_usage": usage,
                "parse_status": "syntax_error"
                if fallback_paths & set(candidate_paths)
                else "parsed",
                "indexed_files": sorted(index.parsed_files),
                "resolution_counts": {
                    "resolved": len(selected),
                    "candidate": len(candidates) - len(selected),
                },
                "coverage_notes": ["Only text-matched definition files were AST parsed."],
            },
            evidence_locations=[*evidence_from_spans(spans), *fallback_evidence],
            truncated=(
                search.truncated
                or len(symbols) > len(selected)
                or len(candidate_paths) < len(all_candidate_paths)
            ),
            truncation_notes=[
                *search.truncation_notes,
                *(
                    ["Some definition candidates used text fallback due to AST limits/errors."]
                    if fallback_paths
                    else []
                ),
            ],
        )

    @staticmethod
    def _expression(name: str, kind: str) -> str:
        if kind == "class":
            return rf"^\s*class\s+{re.escape(name)}\b"
        expression = rf"^\s*(?:async\s+)?def\s+{re.escape(name)}\b"
        if kind == "any":
            expression = (
                rf"^\s*(?:class\s+{re.escape(name)}\b|"
                rf"(?:async\s+)?def\s+{re.escape(name)}\b)"
            )
        return expression

    @staticmethod
    def _kind_matches(requested: str, actual: str) -> bool:
        if requested == "any":
            return actual != "module"
        if requested == "class":
            return actual == "class"
        if requested == "method":
            return actual in {"method", "async_method"}
        return actual in {"function", "async_function"}

    def _text_fallback(
        self, args: FindSymbolInput, search: Observation, step_id: str
    ) -> Observation:
        candidates = []
        for match in search.data.get("matches", []):
            excerpt = str(match["excerpt"])
            detected_kind = "class" if re.search(r"\bclass\s+", excerpt) else "function"
            candidates.append(
                {
                    "path": match["path"],
                    "line": match["line"],
                    "kind": detected_kind,
                    "signature_excerpt": excerpt,
                    "confidence": "candidate",
                    "source": "text_fallback",
                    "resolution": "candidate",
                }
            )
        return Observation(
            step_id=step_id,
            tool_name=self.name,
            status="success",
            summary=f"Found {len(candidates)} text candidates for symbol {args.name}.",
            data={
                "symbol": args.name,
                "candidates": candidates,
                "resolution": "candidate",
                "parse_status": "not_available",
                "indexed_files": [],
                "resolution_counts": {"candidate": len(candidates)},
                "coverage_notes": ["AST Code Index was unavailable; results are text candidates."],
            },
            evidence_locations=search.evidence_locations,
            truncated=search.truncated,
            truncation_notes=search.truncation_notes,
        )
