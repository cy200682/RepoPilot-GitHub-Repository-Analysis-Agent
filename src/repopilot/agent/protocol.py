"""Agent model decision boundary."""

from typing import Protocol, TypedDict

from repopilot.agent.actions import AgentDecision
from repopilot.tools.base import ToolDefinition


class AgentModelUsage(TypedDict):
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated: bool


class AgentModel(Protocol):
    def decide(self, context: str, tools: list[ToolDefinition]) -> AgentDecision: ...
