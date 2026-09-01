from pathlib import Path

from repopilot.config import Settings
from repopilot.models.analysis import AnalysisResult, Evidence
from repopilot.models.repository import RepositorySource
from repopilot.report.evidence import validate_evidence
from repopilot.repository.scanner import RepositoryScanner


def test_evidence_only_verifies_known_safe_paths(
    fixture_repository: Path,
    repository_source: RepositorySource,
) -> None:
    snapshot = RepositoryScanner(Settings()).scan(
        fixture_repository,
        repository_source,
        "abc123",
    )
    result = AnalysisResult(
        project_summary="Sample",
        entrypoint_candidates=[
            "src/sample_service/main.py",
            "src/sample_service/__init__.py",
        ],
        evidence=[
            Evidence(claim="Valid", path="src/sample_service/main.py"),
            Evidence(claim="Escape", path="../secret.txt"),
            Evidence(claim="Invented", path="missing.py"),
        ],
    )

    validated = validate_evidence(result, snapshot)

    assert [item.verified for item in validated.evidence] == [True, False, False]
    assert validated.entrypoint_candidates == ["src/sample_service/main.py"]
    assert any("已移除 1 个" in item for item in validated.limitations)
