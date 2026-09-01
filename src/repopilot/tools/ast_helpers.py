"""Shared helpers for Phase 3 AST tools."""

from __future__ import annotations

from collections.abc import Sequence

from repopilot.agent.state import EvidenceLocation
from repopilot.analysis.code_index import CodeIndex
from repopilot.analysis.models import SourceSpan
from repopilot.analysis.repository_map import RepositoryMap
from repopilot.tools.base import ToolContext


def require_code_index(context: ToolContext) -> CodeIndex:
    if not isinstance(context.code_index, CodeIndex):
        raise ValueError("AST Code Index is not available in this ToolContext.")
    return context.code_index


def require_repository_map(context: ToolContext) -> RepositoryMap:
    if not isinstance(context.repository_map, RepositoryMap):
        raise ValueError("Repository Map is not available in this ToolContext.")
    return context.repository_map


def ast_file_limit(context: ToolContext, configured_limit: int) -> int:
    """Apply the Runtime-owned remaining per-run budget to one AST tool action."""
    if context.ast_file_budget_remaining is None:
        return configured_limit
    return max(min(configured_limit, context.ast_file_budget_remaining), 0)


def resolution_counts(records: Sequence[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        resolution = str(getattr(record, "resolution", "not_applicable"))
        counts[resolution] = counts.get(resolution, 0) + 1
    return counts


def evidence_from_spans(spans: list[SourceSpan]) -> list[EvidenceLocation]:
    unique: dict[tuple[str, int, int], EvidenceLocation] = {}
    for span in spans:
        key = (span.path, span.start_line, span.end_line)
        unique[key] = EvidenceLocation(
            path=span.path, start_line=span.start_line, end_line=span.end_line
        )
    return list(unique.values())


def ast_usage(
    index: CodeIndex,
    before_files: set[str],
    before_nodes: int,
) -> dict[str, object]:
    repository_map = index.repository_map
    return {
        "parsed_files_delta": sorted(index.parsed_files - before_files),
        "ast_nodes_delta": max(index.node_count - before_nodes, 0),
        "map_nodes": len(repository_map.nodes),
        "map_edges": len(repository_map.edges),
        "indexed_files": sorted(index.parsed_files),
        "cache_hits": index.cache_hits,
    }
