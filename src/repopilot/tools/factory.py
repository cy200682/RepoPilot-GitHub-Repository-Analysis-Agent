"""Construct the default read-only Tool Registry and per-run Tool Context."""

from pathlib import Path

from repopilot.analysis.ast_parser import PythonAstParser
from repopilot.analysis.code_index import CodeIndex
from repopilot.analysis.module_index import ModuleIndex
from repopilot.analysis.repository_map import RepositoryMap
from repopilot.config import Settings
from repopilot.models.repository import RepositorySnapshot
from repopilot.repository.reader import RepositoryReaderProtocol
from repopilot.tools.base import ToolContext
from repopilot.tools.inspect_python import InspectPythonTool
from repopilot.tools.memory import RecallMemoryTool, SaveMemoryTool, SearchMemoryTool
from repopilot.tools.read import ReadFileTool
from repopilot.tools.references import FindReferencesTool
from repopilot.tools.registry import ToolRegistry
from repopilot.tools.relationships import GetRelationshipsTool
from repopilot.tools.search import SearchCodeTool
from repopilot.tools.symbols import FindSymbolTool
from repopilot.tools.tree import GetTreeTool


def build_default_registry(settings: Settings) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(GetTreeTool())
    registry.register(ReadFileTool(settings))
    registry.register(SearchCodeTool(settings))
    registry.register(FindSymbolTool(settings))
    registry.register(InspectPythonTool(settings))
    registry.register(FindReferencesTool(settings))
    registry.register(GetRelationshipsTool(settings))
    if settings.memory_enabled:
        registry.register(RecallMemoryTool(settings))
        registry.register(SearchMemoryTool(settings))
        registry.register(SaveMemoryTool(settings))
    return registry


def build_tool_context(
    settings: Settings,
    root_path: Path,
    snapshot: RepositorySnapshot,
    reader: RepositoryReaderProtocol,
    *,
    memory_store: object | None = None,
    memory_repository_id: str | None = None,
    memory_revision_id: str | None = None,
    memory_run_id: str | None = None,
    memory_catalog: dict[str, object] | None = None,
) -> ToolContext:
    """Create a lazy AST index scoped to exactly one Agent run and repository commit."""
    module_index = ModuleIndex(snapshot)
    repository_map = RepositoryMap(snapshot.commit_sha, settings)
    ast_analyzer = PythonAstParser(settings, reader)
    code_index = CodeIndex(root_path, ast_analyzer, module_index, repository_map)
    return ToolContext(
        root_path=root_path,
        snapshot=snapshot,
        reader=reader,
        module_index=module_index,
        code_index=code_index,
        repository_map=repository_map,
        ast_analyzer=ast_analyzer,
        ast_file_budget_remaining=settings.ast_max_files_per_run,
        memory_store=memory_store,
        memory_repository_id=memory_repository_id,
        memory_revision_id=memory_revision_id,
        memory_run_id=memory_run_id,
        memory_catalog=memory_catalog or {},
    )
