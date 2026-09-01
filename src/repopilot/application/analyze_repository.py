"""Phase 1 fixed bootstrap orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repopilot.application.protocols import (
    ContextBuilderProtocol,
    ReportRendererProtocol,
    RepositoryLoaderProtocol,
    RepositoryScannerProtocol,
)
from repopilot.exceptions import ReportWriteError
from repopilot.llm.protocol import LLMClient
from repopilot.models.analysis import AnalysisRequest, AnalysisResult
from repopilot.models.repository import RepositorySnapshot
from repopilot.report.evidence import validate_evidence
from repopilot.report.renderer import MarkdownReportRenderer
from repopilot.repository.url import parse_github_url


@dataclass(slots=True)
class AnalysisOutcome:
    """Useful values returned after a completed Phase 1 run."""

    report_path: Path
    commit_sha: str
    snapshot: RepositorySnapshot
    result: AnalysisResult
    request: AnalysisRequest
    kept_repository_path: Path | None = None


@dataclass(slots=True)
class SnapshotAnalysis:
    request: AnalysisRequest
    result: AnalysisResult


class AnalyzeRepositoryService:
    """Compose Phase 1 capabilities without embedding their implementations."""

    def __init__(
        self,
        loader: RepositoryLoaderProtocol,
        scanner: RepositoryScannerProtocol,
        context_builder: ContextBuilderProtocol,
        llm_client: LLMClient,
        renderer: ReportRendererProtocol | None = None,
    ) -> None:
        self.loader = loader
        self.scanner = scanner
        self.context_builder = context_builder
        self.llm_client = llm_client
        self.renderer = renderer or MarkdownReportRenderer()

    def analyze(
        self,
        repository_url: str,
        output_path: Path,
        *,
        keep_repository: bool = False,
    ) -> AnalysisOutcome:
        source = parse_github_url(repository_url)
        loaded = self.loader.clone(source)
        try:
            snapshot = self.scanner.scan(loaded.root_path, source, loaded.commit_sha)
            analysis = self.analyze_snapshot(snapshot)
            report = self.renderer.render(
                analysis.result,
                snapshot,
                analysis.request.truncation_notes,
            )
            self._write_report(output_path, report)
            return AnalysisOutcome(
                report_path=output_path.resolve(),
                commit_sha=loaded.commit_sha,
                snapshot=snapshot,
                result=analysis.result,
                request=analysis.request,
                kept_repository_path=loaded.root_path if keep_repository else None,
            )
        finally:
            if not keep_repository:
                self.loader.cleanup(loaded)

    def analyze_snapshot(self, snapshot: RepositorySnapshot) -> SnapshotAnalysis:
        request = self.context_builder.build(snapshot)
        result = self.llm_client.analyze_repository(request)
        return SnapshotAnalysis(request=request, result=validate_evidence(result, snapshot))

    @staticmethod
    def _write_report(output_path: Path, report: str) -> None:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise ReportWriteError(f"Could not write report to {output_path}: {exc}") from exc
