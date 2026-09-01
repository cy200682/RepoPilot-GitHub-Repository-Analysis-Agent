from pathlib import Path

from repopilot.config import Settings
from repopilot.models.repository import RepositorySource
from repopilot.repository.scanner import RepositoryScanner


def test_scanner_collects_bounded_repository_facts(
    fixture_repository: Path,
    repository_source: RepositorySource,
) -> None:
    scanner = RepositoryScanner(Settings(max_repo_mb=10, max_files=100))

    snapshot = scanner.scan(fixture_repository, repository_source, "abc123")

    paths = {file.relative_path for file in snapshot.files}
    assert "README.md" in paths
    assert "pyproject.toml" in paths
    assert "src/sample_service/main.py" in paths
    assert not any(path.startswith("node_modules/") for path in paths)
    assert snapshot.readme_path == "README.md"
    assert snapshot.readme_content and "Sample Service" in snapshot.readme_content
    assert any(item.name == "Python" for item in snapshot.detected_languages)
    assert any(item.name == "FastAPI" for item in snapshot.detected_frameworks)
    assert [item.path for item in snapshot.entrypoint_candidates] == ["src/sample_service/main.py"]


def test_scanner_reports_file_limit(
    fixture_repository: Path,
    repository_source: RepositorySource,
) -> None:
    scanner = RepositoryScanner(Settings(max_files=1))

    snapshot = scanner.scan(fixture_repository, repository_source, "abc123")

    assert snapshot.stats.total_files == 1
    assert any("File list was limited" in note for note in snapshot.truncation_notes)
