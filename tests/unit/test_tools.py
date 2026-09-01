from pathlib import Path

from repopilot.agent.actions import ToolAction
from repopilot.config import Settings
from repopilot.models.repository import RepositorySource
from repopilot.repository.reader import RepositoryReader
from repopilot.repository.scanner import RepositoryScanner
from repopilot.tools.base import ToolContext
from repopilot.tools.factory import build_default_registry


def build_context(
    fixture_repository: Path,
    repository_source: RepositorySource,
) -> tuple[Settings, ToolContext]:
    settings = Settings()
    reader = RepositoryReader(settings)
    snapshot = RepositoryScanner(settings, reader).scan(
        fixture_repository, repository_source, "abc123"
    )
    return settings, ToolContext(
        root_path=fixture_repository,
        snapshot=snapshot,
        reader=reader,
    )


def test_default_registry_exposes_phase3_read_only_analysis_tools(
    fixture_repository: Path,
    repository_source: RepositorySource,
) -> None:
    settings, _ = build_context(fixture_repository, repository_source)
    registry = build_default_registry(settings)

    assert [item.name for item in registry.definitions()] == [
        "get_tree",
        "read_file",
        "search_code",
        "find_symbol",
        "inspect_python",
        "find_references",
        "get_relationships",
    ]


def test_tree_read_search_and_symbol_tools(
    fixture_repository: Path,
    repository_source: RepositorySource,
) -> None:
    settings, context = build_context(fixture_repository, repository_source)
    registry = build_default_registry(settings)

    tree = registry.execute(
        ToolAction(tool_name="get_tree", arguments={"path": "src"}), context, "step_tree"
    )
    read = registry.execute(
        ToolAction(
            tool_name="read_file",
            arguments={"path": "src/sample_service/main.py", "start_line": 1, "end_line": 8},
        ),
        context,
        "step_read",
    )
    search = registry.execute(
        ToolAction(tool_name="search_code", arguments={"query": "FastAPI"}),
        context,
        "step_search",
    )
    symbol = registry.execute(
        ToolAction(tool_name="find_symbol", arguments={"name": "health"}),
        context,
        "step_symbol",
    )

    assert tree.status == "success"
    assert "sample_service/main.py" in tree.data["tree"]
    assert read.status == "success"
    assert read.data["start_line"] == 1
    assert read.evidence_locations[0].path == "src/sample_service/main.py"
    assert search.data["total_matches"] >= 1
    assert symbol.data["candidates"][0]["path"] == "src/sample_service/main.py"
    assert symbol.data["candidates"][0]["confidence"] == "candidate"


def test_registry_rejects_unknown_tool_and_path_escape(
    fixture_repository: Path,
    repository_source: RepositorySource,
) -> None:
    settings, context = build_context(fixture_repository, repository_source)
    registry = build_default_registry(settings)

    unknown = registry.execute(
        ToolAction(tool_name="run_command", arguments={"command": "env"}),
        context,
        "step_unknown",
    )
    escaped = registry.execute(
        ToolAction(tool_name="read_file", arguments={"path": "../secret.txt"}),
        context,
        "step_escape",
    )

    assert unknown.status == "error"
    assert "Unknown tool" in unknown.summary
    assert escaped.status == "error"
    assert "inside the repository" in escaped.summary


def test_search_ignores_excluded_directories(
    fixture_repository: Path,
    repository_source: RepositorySource,
) -> None:
    settings, context = build_context(fixture_repository, repository_source)
    result = build_default_registry(settings).execute(
        ToolAction(tool_name="search_code", arguments={"query": "never scan"}),
        context,
        "step_search",
    )

    assert result.status == "success"
    assert result.data["total_matches"] == 0
