import re
from pathlib import Path

from repopilot.agent.actions import (
    AgentAnalysisResult,
    AgentDecision,
    AgentEvidence,
    AgentFinding,
    FinishAction,
    ToolAction,
)
from repopilot.agent.context import AgentContextBuilder
from repopilot.agent.runtime import AgentRuntime
from repopilot.agent.state import AgentState
from repopilot.config import Settings
from repopilot.models.repository import RepositorySource
from repopilot.repository.reader import RepositoryReader
from repopilot.repository.scanner import RepositoryScanner
from repopilot.tools.base import ToolDefinition
from repopilot.tools.factory import build_default_registry, build_tool_context


class AstExploreThenFinishModel:
    def __init__(self) -> None:
        self.calls = 0
        self.api_observation_id = ""

    def decide(self, context: str, tools: list[ToolDefinition]) -> AgentDecision:
        self.calls += 1
        if self.calls == 1:
            return AgentDecision(
                rationale="Inspect the Goal-relevant request handler structure.",
                action=ToolAction(
                    tool_name="inspect_python",
                    arguments={
                        "path": "src/sample_app/api.py",
                        "include": ["symbols", "imports", "calls"],
                    },
                ),
            )
        observation_ids = re.findall(r'"id": "(obs_[a-f0-9]+)"', context)
        if self.calls == 2:
            self.api_observation_id = observation_ids[-1]
            assert "build_service" in context
            return AgentDecision(
                rationale="The handler calls build_service, so inspect its defining module next.",
                action=ToolAction(
                    tool_name="inspect_python",
                    arguments={
                        "path": "src/sample_app/services.py",
                        "include": ["symbols", "inheritances", "calls"],
                    },
                ),
            )
        return AgentDecision(
            rationale="Two targeted AST observations support a bounded report.",
            action=FinishAction(
                analysis=AgentAnalysisResult(
                    project_summary="一个包含异步请求处理与服务层的 Python 示例。",
                    entrypoints=[
                        AgentFinding(
                            claim="handle_request 是 api 模块中的异步请求处理函数。",
                            confidence="confirmed",
                            evidence_ids=["ev_handler"],
                        )
                    ],
                    execution_flows=[
                        AgentFinding(
                            claim="handle_request 静态调用 build_service 创建服务。",
                            confidence="inferred",
                            evidence_ids=["ev_build_call"],
                        )
                    ],
                    evidence=[
                        AgentEvidence(
                            evidence_id="ev_handler",
                            claim="AST 中存在异步函数 handle_request。",
                            path="src/sample_app/api.py",
                            start_line=4,
                            end_line=6,
                            observation_id=self.api_observation_id,
                            source_kind="ast_symbol",
                            resolution="resolved",
                        ),
                        AgentEvidence(
                            evidence_id="ev_build_call",
                            claim="函数体中存在 build_service 调用点。",
                            path="src/sample_app/api.py",
                            start_line=5,
                            end_line=5,
                            observation_id=self.api_observation_id,
                            confidence="inferred",
                            source_kind="ast_call",
                            resolution="unresolved",
                        ),
                    ],
                    limitations=["静态调用点不能证明生产运行时一定执行。"],
                )
            ),
        )


def build_runtime(root: Path, model: object) -> tuple[AgentRuntime, AgentState, object]:
    settings = Settings(agent_max_iterations=5, agent_max_tool_calls=4)
    reader = RepositoryReader(settings)
    source = RepositorySource(
        original_url="https://github.com/example/ast-fixture",
        normalized_url="https://github.com/example/ast-fixture",
        owner="example",
        name="ast-fixture",
        clone_url="https://github.com/example/ast-fixture.git",
    )
    snapshot = RepositoryScanner(settings, reader).scan(root, source, "fixture-sha")
    runtime = AgentRuntime(
        settings,
        model,  # type: ignore[arg-type]
        build_default_registry(settings),
        AgentContextBuilder(settings),
    )
    state = AgentState(
        goal="追踪请求处理到服务创建的静态路径",
        repository_url=source.normalized_url,
        commit_sha=snapshot.commit_sha,
        bootstrap_summary="AST fixture",
    )
    return runtime, state, build_tool_context(settings, root, snapshot, reader)


def test_fake_agent_changes_route_from_ast_observation_and_finishes(
    ast_fixture_repository: Path,
) -> None:
    runtime, state, context = build_runtime(ast_fixture_repository, AstExploreThenFinishModel())

    result = runtime.run(state, context)  # type: ignore[arg-type]

    assert result.state.status == "completed"
    assert [step.observation.tool_name for step in result.trace.steps[:2]] == [
        "inspect_python",
        "inspect_python",
    ]
    assert result.trace.steps[0].observation.data["path"] == "src/sample_app/api.py"
    assert result.trace.steps[1].observation.data["path"] == "src/sample_app/services.py"
    assert result.state.ast_parsed_files == {
        "src/sample_app/api.py",
        "src/sample_app/services.py",
    }
    assert result.state.repository_map_node_count > 0
    assert all(item.verified for item in result.state.final_analysis.evidence)  # type: ignore[union-attr]
