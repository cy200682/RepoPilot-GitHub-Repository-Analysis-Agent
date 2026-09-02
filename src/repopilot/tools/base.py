"""Tool contracts shared by Registry and Agent Runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from repopilot.agent.state import Observation
from repopilot.models.repository import RepositorySnapshot


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolContext(BaseModel):
    root_path: Path
    snapshot: RepositorySnapshot
    reader: Any
    module_index: Any = None
    code_index: Any = None
    repository_map: Any = None
    ast_analyzer: Any = None
    ast_file_budget_remaining: int | None = None
    memory_store: Any = None
    memory_repository_id: str | None = None
    memory_revision_id: str | None = None
    memory_run_id: str | None = None
    memory_catalog: dict[str, Any] = Field(default_factory=dict)
    agent_state: Any = None

    model_config = {"arbitrary_types_allowed": True}


class Tool(Protocol):
    name: str
    description: str
    input_model: type[BaseModel]

    def execute(self, arguments: BaseModel, context: ToolContext, step_id: str) -> Observation: ...


def tool_definition(tool: Tool) -> ToolDefinition:
    return ToolDefinition(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_model.model_json_schema(),
    )
