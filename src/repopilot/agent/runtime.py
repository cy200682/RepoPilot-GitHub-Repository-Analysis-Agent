"""Minimal single-Agent Action/Observation loop."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel

from repopilot.agent.actions import AgentAnalysisResult, ToolAction
from repopilot.agent.context import AgentContextBuilder
from repopilot.agent.finish import FinishGate
from repopilot.agent.protocol import AgentModel
from repopilot.agent.state import AgentState, AgentTrace, Observation, TraceStep, new_id
from repopilot.config import Settings
from repopilot.tools.base import ToolContext
from repopilot.tools.registry import ToolRegistry


class AgentRunResult(BaseModel):
    """Agent 最终返回的状态和完整运行轨迹。"""

    state: AgentState
    trace: AgentTrace


class AgentRuntime:
    """Agent 执行引擎，负责决策循环、工具执行、预算和 Trace。"""

    def __init__(
        self,
        settings: Settings,
        model: AgentModel,
        registry: ToolRegistry,
        context_builder: AgentContextBuilder | None = None,
        finish_gate: FinishGate | None = None,
    ) -> None:
        self.settings = settings
        self.model = model
        self.registry = registry
        self.context_builder = context_builder or AgentContextBuilder(settings)
        self.finish_gate = finish_gate or FinishGate()

    def run(self, state: AgentState, tool_context: ToolContext) -> AgentRunResult:
        trace = AgentTrace(
            run_id=state.run_id,
            repository_url=state.repository_url,
            commit_sha=state.commit_sha,
            goal=state.goal,
        )
        # 工具定义会随每轮 Context 提供给模型。
        definitions = self.registry.definitions()
        while self._can_continue(state):
            state.iteration_count += 1
            step_id = new_id("step")
            context = self.context_builder.build(state, definitions)
            try:
                # 模型在调用工具和提交最终答案之间自主决策。
                decision = self.model.decide(context, definitions)
            except Exception as exc:
                # 决策错误写入 Observation，并受连续错误预算约束。
                self._sync_model_usage(state)
                state.consecutive_error_count += 1
                observation = Observation(
                    step_id=step_id,
                    tool_name="agent_model",
                    status="error",
                    summary=str(exc)[:500],
                )
                state.observations.append(observation)
                trace.steps.append(
                    TraceStep(
                        step_id=step_id,
                        rationale="Model decision failed.",
                        observation_id=observation.id,
                        observation=observation,
                        error=str(exc)[:500],
                    )
                )
                continue
            self._sync_model_usage(state)

            step = TraceStep(step_id=step_id, rationale=decision.rationale, decision=decision)
            if isinstance(decision.action, ToolAction):
                observation = self._execute_tool(decision.action, state, tool_context, step_id)
                state.observations.append(observation)
                state.consecutive_error_count = (
                    0 if observation.status == "success" else state.consecutive_error_count + 1
                )
                self._record_usage(state, observation)
                step.observation_id = observation.id
                step.observation = observation
                trace.steps.append(step)
                continue

            # 非 ToolAction 表示 Agent 请求结束，但仍必须通过 Evidence Gate。
            validation = self.finish_gate.validate(decision.action.analysis, state)
            if validation.accepted:
                state.final_analysis = validation.analysis
                state.memory_entries_cited += self._record_cited_memories(
                    validation.analysis,
                    state,
                    tool_context,
                )
                state.status = "completed"
                trace.steps.append(step)
                break
            observation = Observation(
                step_id=step_id,
                tool_name="finish_gate",
                status="error",
                summary="Finish rejected: " + " ".join(validation.reasons),
                data={"reasons": validation.reasons},
            )
            state.observations.append(observation)
            step.observation_id = observation.id
            step.observation = observation
            trace.steps.append(step)

        if state.status == "running":
            state.status = (
                "budget_exhausted"
                if state.consecutive_error_count < self.settings.agent_max_consecutive_errors
                else "failed"
            )
            state.final_analysis = self._partial_analysis(state)
        trace.ended_at = datetime.now(UTC)
        trace.final_status = state.status
        trace.llm_request_count = state.llm_request_count
        trace.prompt_tokens = state.prompt_tokens
        trace.completion_tokens = state.completion_tokens
        trace.total_tokens = state.total_tokens
        trace.token_usage_estimated = state.token_usage_estimated
        trace.memory_entries_recalled = state.memory_results_seen
        trace.memory_entries_cited = state.memory_entries_cited
        trace.memory_entries_rejected = state.stale_memories_rejected
        trace.memory_entries_refreshed = state.memory_entries_refreshed
        trace.memory_entries_saved = state.memory_entries_saved
        return AgentRunResult(state=state, trace=trace)

    def _can_continue(self, state: AgentState) -> bool:
        return (
            state.status == "running"
            and state.iteration_count < self.settings.agent_max_iterations
            and state.tool_call_count < self.settings.agent_max_tool_calls
            and state.consecutive_error_count < self.settings.agent_max_consecutive_errors
            and len(state.visited_files) < self.settings.agent_max_unique_files
            and state.total_read_chars < self.settings.agent_max_total_read_chars
            and state.total_search_results < self.settings.agent_max_search_results_total
            and state.total_tokens < self.settings.agent_max_total_tokens
            and len(state.ast_parsed_files) < self.settings.ast_max_files_per_run
            and state.ast_node_count
            < self.settings.ast_max_nodes_per_file * self.settings.ast_max_files_per_run
            and state.repository_map_node_count < self.settings.repository_map_max_nodes
            and state.repository_map_edge_count < self.settings.repository_map_max_edges
        )

    def _execute_tool(
        self,
        action: ToolAction,
        state: AgentState,
        context: ToolContext,
        step_id: str,
    ) -> Observation:
        if (
            action.tool_name in {"recall_memory", "search_memory", "save_memory"}
            and state.memory_call_count >= self.settings.memory_max_calls_per_run
        ):
            return Observation(
                step_id=step_id,
                tool_name=action.tool_name,
                status="error",
                summary=(
                    "Memory tool-call budget exhausted; use existing observations or code tools."
                ),
            )
        canonical_arguments = self._canonical_arguments(action.arguments)
        fingerprint = f"{action.tool_name}:{json.dumps(canonical_arguments, sort_keys=True)}"
        count = state.action_counts.get(fingerprint, 0) + 1
        state.action_counts[fingerprint] = count
        if count > self.settings.agent_max_identical_repeats:
            return Observation(
                step_id=step_id,
                tool_name=action.tool_name,
                status="error",
                summary="Repeated action rejected; change the tool or arguments.",
            )
        state.tool_call_count += 1
        context.agent_state = state
        context.ast_file_budget_remaining = max(
            self.settings.ast_max_files_per_run - len(state.ast_parsed_files), 0
        )
        return self.registry.execute(action, context, step_id)

    @classmethod
    def _canonical_arguments(cls, arguments: dict[str, object]) -> dict[str, object]:
        canonical = dict(arguments)
        for key in ("include", "kinds", "types"):
            value = canonical.get(key)
            if isinstance(value, list) and all(isinstance(item, str) for item in value):
                canonical[key] = sorted(value)
        return canonical

    def _sync_model_usage(self, state: AgentState) -> None:
        snapshot_method = getattr(self.model, "usage_snapshot", None)
        if not callable(snapshot_method):
            return
        usage = snapshot_method()
        if not isinstance(usage, dict):
            return
        state.llm_request_count = max(state.llm_request_count, int(usage.get("request_count", 0)))
        state.prompt_tokens = max(state.prompt_tokens, int(usage.get("prompt_tokens", 0)))
        state.completion_tokens = max(
            state.completion_tokens, int(usage.get("completion_tokens", 0))
        )
        state.total_tokens = max(state.total_tokens, int(usage.get("total_tokens", 0)))
        state.token_usage_estimated = state.token_usage_estimated or bool(
            usage.get("estimated", False)
        )

    @staticmethod
    def _record_usage(state: AgentState, observation: Observation) -> None:
        if observation.tool_name in {"recall_memory", "search_memory", "save_memory"}:
            state.memory_call_count += 1
        if observation.status != "success":
            return
        if observation.tool_name == "read_file" and observation.data.get("path"):
            state.visited_files.add(str(observation.data["path"]))
            state.total_read_chars += len(str(observation.data.get("content", "")))
        if observation.tool_name == "search_code" and observation.data.get("query"):
            state.searched_queries.append(str(observation.data["query"]))
            state.total_search_results += int(observation.data.get("total_matches", 0))
        usage = observation.data.get("ast_usage")
        if isinstance(usage, dict):
            parsed_files = usage.get("parsed_files_delta", [])
            if isinstance(parsed_files, list):
                state.ast_parsed_files.update(str(path) for path in parsed_files)
            state.ast_node_count += int(usage.get("ast_nodes_delta", 0))
            state.repository_map_node_count = int(usage.get("map_nodes", 0))
            state.repository_map_edge_count = int(usage.get("map_edges", 0))
            state.ast_cache_hits = max(
                state.ast_cache_hits,
                int(usage.get("cache_hits", 0)),
            )
            if observation.data.get("parse_status") == "syntax_error":
                state.ast_parse_errors += 1
        if observation.tool_name == "find_references":
            state.reference_query_count += 1
        if observation.tool_name == "get_relationships":
            state.relationship_query_count += 1
        if observation.tool_name in {"recall_memory", "search_memory"}:
            state.memory_results_seen += int(observation.data.get("total_matches", 0))
            memories = observation.data.get("memories", [])
            if isinstance(memories, list):
                state.stale_memories_rejected += sum(
                    1
                    for item in memories
                    if isinstance(item, dict) and item.get("status") in {"stale", "invalid"}
                )
                if observation.data.get("content_hash_verified") is True:
                    state.memory_entries_refreshed += sum(
                        1
                        for item in memories
                        if isinstance(item, dict) and item.get("status") == "reusable"
                    )
        if (
            observation.tool_name == "save_memory"
            and observation.status == "success"
            and observation.data.get("deduplicated") is not True
        ):
            state.memory_entries_saved += 1

    @staticmethod
    def _record_cited_memories(
        analysis: AgentAnalysisResult,
        state: AgentState,
        context: ToolContext,
    ) -> int:
        if context.memory_store is None:
            return 0
        observations = {item.id: item for item in state.observations}
        recorded: set[tuple[str, str]] = set()
        for evidence in analysis.evidence:
            if evidence.source_kind != "memory" or not evidence.verified:
                continue
            observation = observations.get(evidence.observation_id)
            if observation is None:
                continue
            memories = observation.data.get("memories", [])
            if not isinstance(memories, list):
                continue
            for memory in memories:
                if not isinstance(memory, dict) or not isinstance(memory.get("memory_id"), str):
                    continue
                nested = memory.get("evidence", [])
                if not isinstance(nested, list) or not any(
                    isinstance(item, dict)
                    and item.get("path") == evidence.path
                    and isinstance(item.get("start_line"), int)
                    and isinstance(item.get("end_line"), int)
                    and int(item["start_line"]) <= evidence.start_line
                    and int(item["end_line"]) >= evidence.end_line
                    for item in nested
                ):
                    continue
                key = (str(memory["memory_id"]), observation.id)
                if key in recorded:
                    continue
                recorded.add(key)
                context.memory_store.record_memory_usage(
                    state.run_id,
                    key[0],
                    observation.id,
                    "cited",
                )
        return len(recorded)

    def _partial_analysis(self, state: AgentState) -> AgentAnalysisResult:
        reached: list[str] = []
        if state.total_tokens >= self.settings.agent_max_total_tokens:
            reached.append(
                f"Token budget reached: {state.total_tokens}/"
                f"{self.settings.agent_max_total_tokens}."
            )
        if state.iteration_count >= self.settings.agent_max_iterations:
            reached.append(
                f"Iteration budget reached: {state.iteration_count}/"
                f"{self.settings.agent_max_iterations}."
            )
        if state.tool_call_count >= self.settings.agent_max_tool_calls:
            reached.append(
                f"Tool-call budget reached: {state.tool_call_count}/"
                f"{self.settings.agent_max_tool_calls}."
            )
        return AgentAnalysisResult(
            project_summary="Agent 未在预算内完成分析。",
            limitations=[
                f"Agent run ended with status {state.status}.",
                f"Iterations: {state.iteration_count}; tool calls: {state.tool_call_count}.",
                f"Model requests: {state.llm_request_count}; tokens: {state.total_tokens}.",
                *(reached or ["A non-token resource or error budget ended the run."]),
            ],
        )
