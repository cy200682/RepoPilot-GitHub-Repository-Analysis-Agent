"""Lazy AST cache and indexes shared by Phase 3 tools in one Agent run."""

from __future__ import annotations

from pathlib import Path

from repopilot.analysis.ast_parser import PythonAstParser
from repopilot.analysis.models import PythonFileAnalysis, SymbolRecord
from repopilot.analysis.module_index import ModuleIndex
from repopilot.analysis.repository_map import RepositoryMap
from repopilot.analysis.resolver import SymbolResolver


class CodeIndex:
    def __init__(
        self,
        root_path: Path,
        parser: PythonAstParser,
        module_index: ModuleIndex,
        repository_map: RepositoryMap,
    ) -> None:
        self.root_path = root_path
        self.parser = parser
        self.module_index = module_index
        self.repository_map = repository_map
        self.analyses: dict[str, PythonFileAnalysis] = {}
        self.cache_hits = 0

    def analyze(self, path: str) -> tuple[PythonFileAnalysis, bool]:
        existing = self.analyses.get(path)
        if existing is not None:
            self.cache_hits += 1
            return existing, True
        analysis = self.parser.parse_file(
            self.root_path, path, self.module_index.module_for_path(path)
        )
        self.analyses[path] = analysis
        self._refresh()
        return self.analyses[path], False

    def _refresh(self) -> None:
        resolver = SymbolResolver(self.module_index)
        raw = list(self.analyses.values())
        known_symbols = [symbol for item in raw for symbol in item.symbols]
        self.analyses = {item.path: resolver.resolve(item, known_symbols) for item in raw}
        self.repository_map.rebuild(self.analyses)

    def symbols_by_name(self, name: str) -> list[SymbolRecord]:
        return [
            symbol
            for analysis in self.analyses.values()
            for symbol in analysis.symbols
            if symbol.name == name
        ]

    @property
    def parsed_files(self) -> set[str]:
        return set(self.analyses)

    @property
    def node_count(self) -> int:
        return sum(item.node_count for item in self.analyses.values())
