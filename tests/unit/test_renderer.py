from pathlib import Path

from repopilot.config import Settings
from repopilot.models.analysis import AnalysisResult
from repopilot.models.repository import RepositorySource
from repopilot.report.renderer import MarkdownReportRenderer
from repopilot.repository.scanner import RepositoryScanner


def test_renderer_includes_context_truncation_notes(
    fixture_repository: Path,
    repository_source: RepositorySource,
) -> None:
    snapshot = RepositoryScanner(Settings()).scan(
        fixture_repository,
        repository_source,
        "abc123",
    )

    report = MarkdownReportRenderer().render(
        AnalysisResult(project_summary="Sample"),
        snapshot,
        ["Context section README was truncated from 100 to 50 characters."],
    )

    assert "Context section README was truncated from 100 to 50 characters." in report
