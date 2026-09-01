"""Bounded incremental map of facts discovered through AST tools."""

from __future__ import annotations

from repopilot.analysis.ast_parser import stable_id
from repopilot.analysis.models import (
    PythonFileAnalysis,
    RepositoryMapEdge,
    RepositoryMapSnapshot,
    SymbolRecord,
)
from repopilot.config import Settings


class RepositoryMap:
    def __init__(self, commit_sha: str, settings: Settings) -> None:
        self.commit_sha = commit_sha
        self.settings = settings
        self.analyses: dict[str, PythonFileAnalysis] = {}
        self.nodes: dict[str, SymbolRecord] = {}
        self.edges: dict[str, RepositoryMapEdge] = {}
        self.parse_errors: dict[str, str] = {}
        self.truncated = False
        self.truncation_notes: list[str] = []

    def rebuild(self, analyses: dict[str, PythonFileAnalysis]) -> None:
        self.analyses = dict(analyses)
        self.nodes.clear()
        self.edges.clear()
        self.parse_errors.clear()
        self.truncated = False
        self.truncation_notes.clear()
        for analysis in analyses.values():
            if analysis.syntax_error:
                self.parse_errors[analysis.path] = analysis.syntax_error
            for symbol in analysis.symbols:
                self._add_node(symbol)
            for symbol in analysis.symbols:
                if symbol.parent_symbol_id:
                    self._add_edge(
                        RepositoryMapEdge(
                            relationship_id=stable_id(
                                "defines", symbol.parent_symbol_id, symbol.symbol_id
                            ),
                            relationship_type="defines",
                            source_id=symbol.parent_symbol_id,
                            target_id=symbol.symbol_id,
                            span=symbol.span,
                            resolution="resolved",
                        )
                    )
            module_id = f"{analysis.module_name}:<module>"
            for import_record in analysis.imports:
                target_id = (
                    f"{import_record.resolved_module}:<module>"
                    if import_record.resolved_module and import_record.resolution == "resolved"
                    else None
                )
                self._add_edge(
                    RepositoryMapEdge(
                        relationship_id=import_record.import_id,
                        relationship_type="imports",
                        source_id=module_id,
                        target_id=target_id,
                        target_expression=import_record.module or import_record.imported_name,
                        span=import_record.span,
                        resolution=import_record.resolution,
                    )
                )
            for inheritance in analysis.inheritances:
                self._add_edge(
                    RepositoryMapEdge(
                        relationship_id=inheritance.relationship_id,
                        relationship_type="inherits",
                        source_id=inheritance.subclass_symbol_id,
                        target_id=inheritance.resolved_base_symbol_id,
                        target_expression=inheritance.base_expression,
                        span=inheritance.span,
                        resolution=inheritance.resolution,
                    )
                )
            for call in analysis.calls:
                self._add_edge(
                    RepositoryMapEdge(
                        relationship_id=call.call_id,
                        relationship_type="calls",
                        source_id=call.caller_symbol_id,
                        target_id=call.resolved_symbol_id,
                        target_expression=call.callee_expression,
                        span=call.span,
                        resolution=call.resolution,
                    )
                )
            for reference in analysis.references:
                self._add_edge(
                    RepositoryMapEdge(
                        relationship_id=reference.reference_id,
                        relationship_type="references",
                        source_id=reference.enclosing_symbol_id,
                        target_id=reference.resolved_symbol_id,
                        target_expression=reference.symbol_name,
                        span=reference.span,
                        resolution=reference.resolution,
                    )
                )

    def _add_node(self, node: SymbolRecord) -> None:
        if len(self.nodes) >= self.settings.repository_map_max_nodes:
            self._truncate(
                f"Repository Map nodes limited to {self.settings.repository_map_max_nodes}."
            )
            return
        self.nodes[node.symbol_id] = node

    def _add_edge(self, edge: RepositoryMapEdge) -> None:
        if len(self.edges) >= self.settings.repository_map_max_edges:
            self._truncate(
                f"Repository Map edges limited to {self.settings.repository_map_max_edges}."
            )
            return
        self.edges[edge.relationship_id] = edge

    def _truncate(self, note: str) -> None:
        self.truncated = True
        if note not in self.truncation_notes:
            self.truncation_notes.append(note)

    def query(
        self,
        *,
        symbol_id: str | None = None,
        path: str | None = None,
        direction: str = "both",
        relationship_types: set[str] | None = None,
        max_depth: int = 1,
        max_results: int = 200,
    ) -> list[RepositoryMapEdge]:
        results: dict[str, RepositoryMapEdge] = {}
        path_symbols = {
            item.symbol_id for item in self.nodes.values() if path is None or item.path == path
        }
        frontier = {symbol_id} if symbol_id else path_symbols
        visited = set(frontier)
        ordered_edges = sorted(
            self.edges.values(),
            key=lambda item: (item.span.path, item.span.start_line, item.relationship_type),
        )
        for _ in range(max_depth):
            next_frontier: set[str] = set()
            for edge in ordered_edges:
                if relationship_types and edge.relationship_type not in relationship_types:
                    continue
                incoming = edge.target_id in frontier
                outgoing = edge.source_id in frontier
                if direction == "incoming" and not incoming:
                    continue
                if direction == "outgoing" and not outgoing:
                    continue
                if direction == "both" and not (incoming or outgoing):
                    continue
                results[edge.relationship_id] = edge
                for endpoint in (edge.source_id, edge.target_id):
                    if endpoint and endpoint not in visited:
                        next_frontier.add(endpoint)
            if len(results) >= max_results or not next_frontier:
                break
            visited.update(next_frontier)
            frontier = next_frontier
        return list(results.values())[:max_results]

    def snapshot(self) -> RepositoryMapSnapshot:
        return RepositoryMapSnapshot(
            repository_commit=self.commit_sha,
            indexed_files=sorted(self.analyses),
            nodes=list(self.nodes.values()),
            edges=list(self.edges.values()),
            parse_errors=dict(self.parse_errors),
            truncated=self.truncated,
            truncation_notes=list(self.truncation_notes),
        )
