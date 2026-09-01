from pathlib import Path

from repopilot.agent.actions import ToolAction
from repopilot.config import Settings
from repopilot.models.repository import RepositorySource
from repopilot.repository.reader import RepositoryReader
from repopilot.repository.scanner import RepositoryScanner
from repopilot.tools.factory import build_default_registry, build_tool_context


def build_ast_tool_fixture(root: Path):  # type: ignore[no-untyped-def]
    settings = Settings(ast_max_files_per_run=10, ast_max_files_per_tool=5)
    reader = RepositoryReader(settings)
    source = RepositorySource(
        original_url="https://github.com/example/ast-fixture",
        normalized_url="https://github.com/example/ast-fixture",
        owner="example",
        name="ast-fixture",
        clone_url="https://github.com/example/ast-fixture.git",
    )
    snapshot = RepositoryScanner(settings, reader).scan(root, source, "fixture-sha")
    return (
        settings,
        build_default_registry(settings),
        build_tool_context(settings, root, snapshot, reader),
    )


def test_phase3_tools_return_ast_observations_and_map_coverage(
    ast_fixture_repository: Path,
) -> None:
    _, registry, context = build_ast_tool_fixture(ast_fixture_repository)

    inspection = registry.execute(
        ToolAction(
            tool_name="inspect_python",
            arguments={
                "path": "src/sample_app/services.py",
                "include": ["symbols", "imports", "inheritances", "calls"],
            },
        ),
        context,
        "step_inspect",
    )
    symbol = registry.execute(
        ToolAction(tool_name="find_symbol", arguments={"name": "BaseService"}),
        context,
        "step_symbol",
    )
    references = registry.execute(
        ToolAction(tool_name="find_references", arguments={"name": "build_service"}),
        context,
        "step_references",
    )
    relationships = registry.execute(
        ToolAction(
            tool_name="get_relationships",
            arguments={"symbol_id": "sample_app.services:GreetingService"},
        ),
        context,
        "step_relationships",
    )

    assert inspection.status == "success"
    assert inspection.data["module_name"] == "sample_app.services"
    assert inspection.data["ast_usage"]["parsed_files_delta"] == ["src/sample_app/services.py"]
    assert inspection.evidence_locations
    assert symbol.status == "success"
    assert symbol.data["resolution"] == "exact"
    assert symbol.data["candidates"][0]["source"] == "ast"
    assert references.status == "success"
    assert references.data["references"]
    assert relationships.status == "success"
    assert relationships.data["indexed_files"]
    assert relationships.data["coverage_notes"]


def test_ast_tool_obeys_runtime_remaining_file_budget(ast_fixture_repository: Path) -> None:
    _, registry, context = build_ast_tool_fixture(ast_fixture_repository)
    context.ast_file_budget_remaining = 0

    result = registry.execute(
        ToolAction(
            tool_name="inspect_python",
            arguments={"path": "src/sample_app/services.py"},
        ),
        context,
        "step_budget",
    )

    assert result.status == "success"
    assert result.truncated is True
    assert result.data["parse_status"] == "skipped"
    assert "budget exhausted" in result.summary
