from pathlib import Path

from repopilot.application.analyze_repository import AnalyzeRepositoryService
from repopilot.config import Settings
from repopilot.context.builder import ContextBuilder
from repopilot.models.analysis import AnalysisRequest, AnalysisResult, Evidence
from repopilot.models.repository import RepositorySource
from repopilot.report.renderer import MarkdownReportRenderer
from repopilot.repository.loader import LoadedRepository
from repopilot.repository.scanner import RepositoryScanner


class FakeLoader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.cleaned = False

    def clone(self, source: RepositorySource) -> LoadedRepository:
        return LoadedRepository(source, self.root, "abc123", self.root)

    def cleanup(self, _: LoadedRepository) -> None:
        self.cleaned = True


class FakeLLMClient:
    def analyze_repository(self, request: AnalysisRequest) -> AnalysisResult:
        assert "Sample Service" in request.context
        return AnalysisResult(
            project_summary="A small HTTP service fixture.",
            technology_stack=["Python", "FastAPI"],
            directory_overview=["src/ contains application code."],
            entrypoint_candidates=["src/sample_service/main.py"],
            core_module_candidates=["sample_service.main"],
            evidence=[
                Evidence(
                    claim="The fixture exposes a FastAPI application.",
                    path="src/sample_service/main.py",
                )
            ],
            limitations=["Only fixture context was analyzed."],
            recommended_reading_order=["src/sample_service/main.py"],
        )


def test_fixture_to_markdown_report(
    tmp_path: Path,
    fixture_repository: Path,
) -> None:
    settings = Settings()
    loader = FakeLoader(fixture_repository)
    service = AnalyzeRepositoryService(
        loader=loader,
        scanner=RepositoryScanner(settings),
        context_builder=ContextBuilder(settings),
        llm_client=FakeLLMClient(),
        renderer=MarkdownReportRenderer(),
    )
    output = tmp_path / "REPORT.md"

    outcome = service.analyze(
        "https://github.com/example/sample-service",
        output,
    )

    report = output.read_text(encoding="utf-8")
    assert outcome.commit_sha == "abc123"
    assert "# Repository Analysis" in report
    assert "A small HTTP service fixture." in report
    assert "(verified)" in report
    assert loader.cleaned is True
