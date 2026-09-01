from pathlib import Path

from repopilot.config import Settings
from repopilot.context.builder import ContextBuilder
from repopilot.models.repository import RepositorySource
from repopilot.repository.scanner import RepositoryScanner


def test_context_builder_honors_budget(
    fixture_repository: Path,
    repository_source: RepositorySource,
) -> None:
    settings = Settings(context_char_budget=1_200)
    snapshot = RepositoryScanner(settings).scan(fixture_repository, repository_source, "abc123")
    snapshot = snapshot.model_copy(update={"readme_content": "x" * 5_000})

    request = ContextBuilder(settings).build(snapshot)

    assert len(request.context) <= 1_200
    assert "Repository metadata" in request.context
    assert "Directory tree" in request.context
    assert request.truncated is True
    assert request.truncation_notes
    assert any("Context" in note for note in request.truncation_notes)


def test_context_keeps_deterministic_findings_before_large_dependencies(
    fixture_repository: Path,
    repository_source: RepositorySource,
) -> None:
    settings = Settings(context_char_budget=1_200)
    snapshot = RepositoryScanner(settings).scan(fixture_repository, repository_source, "abc123")
    snapshot = snapshot.model_copy(
        update={"dependency_contents": {"large.lock": "dependency-data" * 1_000}}
    )

    request = ContextBuilder(settings).build(snapshot)

    assert "Deterministic scan findings" in request.context
    assert "Entrypoint candidate: src/sample_service/main.py" in request.context
    assert any("Dependency files" in note for note in request.truncation_notes)
