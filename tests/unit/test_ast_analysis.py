from pathlib import Path

from repopilot.analysis.ast_parser import PythonAstParser
from repopilot.analysis.code_index import CodeIndex
from repopilot.analysis.module_index import ModuleIndex
from repopilot.analysis.repository_map import RepositoryMap
from repopilot.config import Settings
from repopilot.models.repository import RepositorySource
from repopilot.repository.reader import RepositoryReader
from repopilot.repository.scanner import RepositoryScanner


def build_index(root: Path) -> tuple[CodeIndex, ModuleIndex]:
    settings = Settings()
    reader = RepositoryReader(settings)
    source = RepositorySource(
        original_url="https://github.com/example/ast-fixture",
        normalized_url="https://github.com/example/ast-fixture",
        owner="example",
        name="ast-fixture",
        clone_url="https://github.com/example/ast-fixture.git",
    )
    snapshot = RepositoryScanner(settings, reader).scan(root, source, "fixture-sha")
    modules = ModuleIndex(snapshot)
    repository_map = RepositoryMap(snapshot.commit_sha, settings)
    parser = PythonAstParser(settings, reader)
    return CodeIndex(root, parser, modules, repository_map), modules


def test_ast_parser_extracts_symbols_imports_calls_and_spans(
    ast_fixture_repository: Path,
) -> None:
    index, modules = build_index(ast_fixture_repository)

    analysis, cached = index.analyze("src/sample_app/services.py")

    assert cached is False
    assert modules.module_for_path(analysis.path) == "sample_app.services"
    assert analysis.parse_status == "parsed"
    assert {(item.name, item.kind) for item in analysis.symbols} >= {
        ("GreetingService", "class"),
        ("execute", "method"),
        ("format_message", "method"),
        ("build_service", "function"),
    }
    greeting = next(item for item in analysis.symbols if item.name == "GreetingService")
    assert greeting.docstring_summary == "Build greeting messages."
    assert greeting.span.path == analysis.path
    assert greeting.span.start_line == 4
    assert any(item.imported_name == "BaseService" and item.level == 1 for item in analysis.imports)
    assert any(item.callee_expression == "self.format_message" for item in analysis.calls)
    assert any(item.reference_kind == "base" for item in analysis.references)


def test_lazy_index_resolves_unambiguous_local_relationships_and_builds_map(
    ast_fixture_repository: Path,
) -> None:
    index, _ = build_index(ast_fixture_repository)
    index.analyze("src/sample_app/base.py")
    services, _ = index.analyze("src/sample_app/services.py")
    index.analyze("src/sample_app/api.py")

    inheritance = services.inheritances[0]
    assert inheritance.resolution == "resolved"
    assert inheritance.resolved_base_symbol_id == "sample_app.base:BaseService"
    self_call = next(
        item for item in services.calls if item.callee_expression == "self.format_message"
    )
    assert self_call.resolution == "resolved"
    assert self_call.resolved_symbol_id == "sample_app.services:GreetingService.format_message"
    build_call = next(
        item
        for item in index.analyses["src/sample_app/api.py"].calls
        if item.callee_expression == "build_service"
    )
    assert build_call.resolution == "resolved"
    assert build_call.resolved_symbol_id == "sample_app.services:build_service"
    assert len(index.repository_map.nodes) >= 9
    assert {item.relationship_type for item in index.repository_map.edges.values()} >= {
        "defines",
        "imports",
        "inherits",
        "calls",
        "references",
    }


def test_ast_syntax_error_and_cache_are_explicit(ast_fixture_repository: Path) -> None:
    index, _ = build_index(ast_fixture_repository)

    broken, first_cached = index.analyze("src/sample_app/broken.py")
    second, second_cached = index.analyze("src/sample_app/broken.py")

    assert first_cached is False
    assert second_cached is True
    assert second is broken
    assert broken.parse_status == "syntax_error"
    assert broken.syntax_error
    assert index.cache_hits == 1


def test_ast_node_budget_stops_extraction(ast_fixture_repository: Path) -> None:
    settings = Settings(ast_max_nodes_per_file=5)
    reader = RepositoryReader(settings)
    source = RepositorySource(
        original_url="https://github.com/example/ast-fixture",
        normalized_url="https://github.com/example/ast-fixture",
        owner="example",
        name="ast-fixture",
        clone_url="https://github.com/example/ast-fixture.git",
    )
    snapshot = RepositoryScanner(settings, reader).scan(
        ast_fixture_repository, source, "fixture-sha"
    )
    parser = PythonAstParser(settings, reader)

    result = parser.parse_file(
        ast_fixture_repository,
        "src/sample_app/services.py",
        ModuleIndex(snapshot).module_for_path("src/sample_app/services.py"),
    )

    assert result.parse_status == "truncated"
    assert result.node_count == 5
    assert any("traversal limited" in note for note in result.truncation_notes)
