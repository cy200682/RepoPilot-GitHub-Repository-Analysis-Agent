"""Replaceable capability boundaries used by application orchestration."""

from pathlib import Path
from typing import Protocol

from repopilot.models.analysis import AnalysisRequest, AnalysisResult
from repopilot.models.repository import RepositorySnapshot, RepositorySource
from repopilot.repository.loader import LoadedRepository


class RepositoryLoaderProtocol(Protocol):
    def clone(self, source: RepositorySource) -> LoadedRepository: ...

    def cleanup(self, loaded: LoadedRepository) -> None: ...


class RepositoryScannerProtocol(Protocol):
    def scan(
        self,
        root_path: Path,
        source: RepositorySource,
        commit_sha: str,
    ) -> RepositorySnapshot: ...


class ContextBuilderProtocol(Protocol):
    def build(self, snapshot: RepositorySnapshot) -> AnalysisRequest: ...


class ReportRendererProtocol(Protocol):
    def render(
        self,
        result: AnalysisResult,
        snapshot: RepositorySnapshot,
        context_truncation_notes: list[str] | None = None,
    ) -> str: ...
