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
from repopilot.memory.database import MemoryDatabase
from repopilot.memory.repository import SqliteMemoryStore
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


class RecallThenAnswerModel:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, context: str, tools: list[ToolDefinition]) -> AgentDecision:
        self.calls += 1
        if self.calls == 1:
            assert '"current_revision_memories": 1' in context
            return AgentDecision(
                rationale="当前 Commit 已有入口记忆，先召回。",
                action=ToolAction(
                    tool_name="recall_memory",
                    arguments={"memory_types": ["entry_point"]},
                ),
            )
        observation_id = re.findall(r'"id": "(obs_[a-f0-9]+)"', context)[-1]
        return AgentDecision(
            rationale="召回的当前版本 Evidence 足以回答追问。",
            action=FinishAction(
                analysis=AgentAnalysisResult(
                    project_summary="入口仍位于 main.py。",
                    entrypoints=[
                        AgentFinding(
                            claim="src/sample_service/main.py 创建 FastAPI 应用。",
                            confidence="confirmed",
                            evidence_ids=["ev_recalled"],
                        )
                    ],
                    evidence=[
                        AgentEvidence(
                            evidence_id="ev_recalled",
                            claim="当前 Commit Memory 中的入口证据。",
                            path="src/sample_service/main.py",
                            start_line=3,
                            end_line=3,
                            observation_id=observation_id,
                            source_kind="memory",
                            resolution="not_applicable",
                        )
                    ],
                    limitations=["只回答当前入口追问。"],
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


def test_agent_service_persists_verified_memory_and_conversation(
    tmp_path: Path,
    fixture_repository: Path,
) -> None:
    settings = Settings(memory_database=tmp_path / "memory.db")
    reader = RepositoryReader(settings)
    store = SqliteMemoryStore(MemoryDatabase(settings.memory_database))
    runtime = AgentRuntime(
        settings,
        SearchThenFinishModel(),
        build_default_registry(settings),
        AgentContextBuilder(settings),
    )
    service = AnalyzeRepositoryAgentService(
        loader=FakeLoader(fixture_repository),
        scanner=RepositoryScanner(settings, reader),
        reader=reader,
        runtime=runtime,
        memory_store=store,
    )

    outcome = service.analyze(
        "https://github.com/example/sample-service",
        tmp_path / "answer.md",
        goal="回答入口在哪里",
        question="入口在哪里？",
    )

    stats = store.stats()
    assert outcome.state.status == "completed"
    assert outcome.conversation_id is not None
    assert stats.runs == 1
    assert stats.memories == 1
    assert stats.conversations == 1
    assert stats.messages == 2
    assert outcome.state.memory_entries_saved == 1
    assert "Memory entries saved: 1" in (tmp_path / "answer.md").read_text(encoding="utf-8")
    memories = store.list_memories()
    assert memories[0].memory_type == "entry_point"
    assert memories[0].evidence[0].verified is True
    assert memories[0].evidence[0].content_hash is not None
    messages = store.list_messages(outcome.conversation_id)
    assert [item.role for item in messages] == ["user", "assistant"]

    second_runtime = AgentRuntime(
        settings,
        RecallThenAnswerModel(),
        build_default_registry(settings),
        AgentContextBuilder(settings),
    )
    second_service = AnalyzeRepositoryAgentService(
        loader=FakeLoader(fixture_repository),
        scanner=RepositoryScanner(settings, reader),
        reader=reader,
        runtime=second_runtime,
        memory_store=store,
    )
    second = second_service.analyze(
        "https://github.com/example/sample-service",
        tmp_path / "answer-2.md",
        goal="它仍然是入口吗",
        question="它仍然是入口吗？",
        conversation_id=outcome.conversation_id,
    )

    assert second.state.status == "completed"
    assert second.state.memory_call_count == 1
    assert second.state.memory_entries_cited == 1
    assert len(store.list_messages(outcome.conversation_id)) == 4
