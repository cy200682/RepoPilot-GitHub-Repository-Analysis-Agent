"""Schema-validating Tool Registry without decision logic."""

from time import perf_counter

from pydantic import ValidationError

from repopilot.agent.actions import ToolAction
from repopilot.agent.state import Observation
from repopilot.tools.base import Tool, ToolContext, ToolDefinition, tool_definition


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def definitions(self) -> list[ToolDefinition]:
        return [tool_definition(tool) for tool in self._tools.values()]

    def execute(self, action: ToolAction, context: ToolContext, step_id: str) -> Observation:
        started = perf_counter()
        tool = self._tools.get(action.tool_name)
        if tool is None:
            return self._error(step_id, action.tool_name, f"Unknown tool: {action.tool_name}")
        try:
            arguments = tool.input_model.model_validate(action.arguments)
            observation = tool.execute(arguments, context, step_id)
        except ValidationError as exc:
            observation = self._error(step_id, action.tool_name, f"Invalid arguments: {exc}")
        except Exception as exc:
            observation = self._error(step_id, action.tool_name, f"Tool failed: {exc}")
        observation.duration_ms = int((perf_counter() - started) * 1000)
        return observation

    @staticmethod
    def _error(step_id: str, tool_name: str, summary: str) -> Observation:
        return Observation(
            step_id=step_id,
            tool_name=tool_name,
            status="error",
            summary=summary[:500],
        )
