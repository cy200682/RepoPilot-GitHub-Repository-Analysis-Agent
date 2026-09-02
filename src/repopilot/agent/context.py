"""Bounded Agent prompt context construction."""

import json

from repopilot.agent.state import AgentState, Observation
from repopilot.config import Settings
from repopilot.models.repository import RepositorySnapshot
from repopilot.tools.base import ToolDefinition


def build_bootstrap_summary(snapshot: RepositorySnapshot) -> str:
    facts = {
        "repository": f"{snapshot.source.owner}/{snapshot.source.name}",
        "commit_sha": snapshot.commit_sha,
        "stats": snapshot.stats.model_dump(mode="json"),
        "languages": [item.model_dump(mode="json") for item in snapshot.detected_languages],
        "frameworks": [item.model_dump(mode="json") for item in snapshot.detected_frameworks],
        "entrypoint_candidates": [
            item.model_dump(mode="json") for item in snapshot.entrypoint_candidates
        ],
        "tree": snapshot.directory_tree[:15_000],
        "readme_excerpt": (snapshot.readme_content or "")[:8_000],
        "scan_limitations": snapshot.truncation_notes,
    }
    return json.dumps(facts, ensure_ascii=False, indent=2)


class AgentContextBuilder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build(self, state: AgentState, tools: list[ToolDefinition]) -> str:
        recent_count = self.settings.agent_recent_observations
        older = state.observations[:-recent_count]
        recent = state.observations[-recent_count:]
        sections = [
            f"# Goal\n{state.goal}",
            (
                "# Budget\n"
                f"iterations: {state.iteration_count}/{self.settings.agent_max_iterations}\n"
                f"tool calls: {state.tool_call_count}/{self.settings.agent_max_tool_calls}"
                f"\nAST files: {len(state.ast_parsed_files)}/"
                f"{self.settings.ast_max_files_per_run}"
                f"\ntokens: {state.total_tokens}/{self.settings.agent_max_total_tokens}"
            ),
            f"# Available tools\n{self._json([tool.model_dump() for tool in tools])}",
            (
                "# Finish requirements\n"
                "Every entrypoint, core module, execution flow, and module relationship must be "
                "a structured Finding with confidence and evidence_ids. Every evidence_id must "
                "refer to submitted Evidence grounded in an Observation path and line range. "
                "Evidence must declare source_kind and resolution matching its producing tool. "
                "AST and Repository Map results describe only Agent-explored files; treat "
                "ambiguous, candidate, and unresolved relationships as non-confirmed. "
                "get_tree is navigation-only and cannot be submitted as line Evidence. "
                "Inferred and candidate Findings still need supporting Evidence. If Evidence is "
                "insufficient, use another tool. Before finish, verify every critical Finding has "
                "at least one evidence_id. Never combine disjoint returned spans into a broad "
                "Evidence range. Attempt finish with at least two iterations remaining."
                " Execution-flow Findings must be inferred because static code cannot prove "
                "runtime execution."
            ),
            (
                "# Recent observations\n"
                f"{self._json([self._compact_observation(item) for item in recent])}"
            ),
            f"# Repository bootstrap facts\n{self._bootstrap(state)}",
            f"# Visited files\n{self._json(sorted(state.visited_files))}",
            f"# Search history\n{self._json(state.searched_queries[-20:])}",
            (
                "# Repository memory catalog\n"
                f"{self._json(state.memory_catalog) if state.memory_catalog else '(none)'}\n"
                "This catalog only announces available historical memory. Use a memory tool "
                "to inspect it; do not assume it is current or sufficient."
            ),
            (f"# Conversation summary\n{state.conversation_summary or '(none)'}"),
            (f"# Recent conversation messages\n{self._json(self._recent_messages(state))}"),
            (
                "# Code index coverage\n"
                f"parsed files: {len(state.ast_parsed_files)}\n"
                f"parse errors: {state.ast_parse_errors}\n"
                f"map nodes: {state.repository_map_node_count}\n"
                f"map edges: {state.repository_map_edge_count}"
                f"\nmemory calls: {state.memory_call_count}/"
                f"{self.settings.memory_max_calls_per_run}"
                f"\nmemory candidates seen: {state.memory_results_seen}"
            ),
            f"# Older observation summaries\n{self._older_summaries(older)}",
        ]
        return self._fit("\n\n".join(sections))

    @staticmethod
    def _older_summaries(observations: list[Observation]) -> str:
        return (
            "\n".join(AgentContextBuilder._older_summary(item) for item in observations) or "(none)"
        )

    @staticmethod
    def _older_summary(item: Observation) -> str:
        locations = json.dumps([location.model_dump() for location in item.evidence_locations])
        return f"- {item.id} [{item.tool_name}/{item.status}]: {item.summary}; evidence={locations}"

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2)

    def _recent_messages(self, state: AgentState) -> list[str]:
        return state.recent_messages[-self.settings.conversation_recent_messages :]

    @classmethod
    def _bootstrap(cls, state: AgentState) -> str:
        if state.iteration_count <= 1:
            return state.bootstrap_summary
        try:
            value = json.loads(state.bootstrap_summary)
        except json.JSONDecodeError:
            return state.bootstrap_summary[:4_000]
        if not isinstance(value, dict):
            return state.bootstrap_summary[:4_000]
        compact = dict(value)
        compact.pop("readme_excerpt", None)
        tree = compact.get("tree")
        if isinstance(tree, str) and len(tree) > 3_000:
            compact["tree"] = tree[:3_000] + "\n[bootstrap tree truncated after first turn]"
        return cls._json(compact)

    @classmethod
    def _compact_observation(cls, observation: Observation) -> dict[str, object]:
        value = observation.model_dump(mode="json")
        value["data"] = cls._compact_value(value["data"], depth=0)
        return value

    @classmethod
    def _compact_value(cls, value: object, *, depth: int) -> object:
        if depth >= 6:
            return "[nested data omitted]"
        if isinstance(value, str):
            return value[:1_000] + ("[truncated]" if len(value) > 1_000 else "")
        if isinstance(value, list):
            selected = [cls._compact_value(item, depth=depth + 1) for item in value[:20]]
            if len(value) > 20:
                selected.append(f"[{len(value) - 20} additional items omitted]")
            return selected
        if isinstance(value, dict):
            return {
                str(key): cls._compact_value(item, depth=depth + 1) for key, item in value.items()
            }
        return value

    def _fit(self, context: str) -> str:
        budget = self.settings.agent_context_char_budget
        if len(context) <= budget:
            return context
        return context[:budget] + "\n[Agent context truncated by runtime budget]"
