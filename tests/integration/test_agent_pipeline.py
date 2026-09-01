import json
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
from repopilot.application.analyze_repository_agent import AnalyzeRepositoryAgentService
from repopilot.config import Settings
from repopilot.models.repository import RepositorySource
from repopilot.repository.loader import LoadedRepository
from repopilot.repository.reader import RepositoryReader
from repopilot.repository.scanner import RepositoryScanner
from repopilot.tools.base import ToolDefinition
from repopilot.tools.factory import build_default_registry


class FakeLoader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.cleaned = False

    def clone(self, source: RepositorySource) -> LoadedRepository:
        return LoadedRepository(source, self.root, "abc123", self.root)

    def cleanup(self, loaded: LoadedRepository) -> None:
        self.cleaned = True


class SearchThenFinishModel:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, context: str, tools: list[ToolDefinition]) -> AgentDecision:
        self.calls += 1
        if self.calls == 1:
            return AgentDecision(
                rationale="搜索 FastAPI 应用创建位置。",
                action=ToolAction(tool_name="search_code", arguments={"query": "FastAPI()"}),
            )
        observation_id = re.findall(r'"id": "(obs_[a-f0-9]+)"', context)[-1]
        return AgentDecision(
            rationale="搜索结果提供了入口证据。",
            action=FinishAction(
                analysis=AgentAnalysisResult(
                    project_summary="一个 FastAPI Fixture。",
                    entrypoints=[
                        AgentFinding(
                            claim="src/sample_service/main.py 创建 FastAPI 应用。",
                            confidence="confirmed",
                            evidence_ids=["ev_entry"],
                        )
                    ],
                    evidence=[
                        AgentEvidence(
                            evidence_id="ev_entry",
                            claim="main.py 创建 FastAPI 应用。",
                            path="src/sample_service/main.py",
                            start_line=3,
                            end_line=3,
                            observation_id=observation_id,
                            source_kind="search",
                        )
                    ],
                    limitations=["仅用于集成测试。"],
                )
            ),
        )


def test_agent_service_writes_report_and_trace(
    tmp_path: Path,
    fixture_repository: Path,
) -> None:
    settings = Settings()
    reader = RepositoryReader(settings)
    loader = FakeLoader(fixture_repository)
    runtime = AgentRuntime(
        settings,
        SearchThenFinishModel(),
        build_default_registry(settings),
        AgentContextBuilder(settings),
    )
    service = AnalyzeRepositoryAgentService(
        loader=loader,
        scanner=RepositoryScanner(settings, reader),
        reader=reader,
        runtime=runtime,
    )
    report_path = tmp_path / "REPORT.md"
    trace_path = tmp_path / "trace.json"

    outcome = service.analyze(
        "https://github.com/example/sample-service",
        report_path,
        goal="找到 Web 入口",
        trace_output=trace_path,
    )

    report = report_path.read_text(encoding="utf-8")
    trace_text = trace_path.read_text(encoding="utf-8")
    trace = json.loads(trace_text)
    assert outcome.state.status == "completed"
    assert "一个 FastAPI Fixture" in report
    assert "[confirmed] src/sample_service/main.py 创建 FastAPI 应用" in report
    assert "Evidence: `ev_entry`" in report
    assert "`ev_entry` [confirmed]" in report
    assert "observation `obs_" in report
    assert trace["final_status"] == "completed"
    assert trace["steps"][0]["observation"]["tool_name"] == "search_code"
    assert trace["steps"][0]["observation"]["evidence_locations"]
    assert loader.cleaned is True
