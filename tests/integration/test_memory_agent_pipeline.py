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
from repopilot.memory.database import MemoryDatabase
from repopilot.memory.models import MemoryCandidate, MemoryEvidence
from repopilot.memory.repository import SqliteMemoryStore
from repopilot.models.repository import RepositorySource
from repopilot.repository.reader import RepositoryReader
from repopilot.repository.scanner import RepositoryScanner
from repopilot.tools.base import ToolDefinition
from repopilot.tools.factory import build_default_registry, build_tool_context


class RecallThenFinishModel:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, context: str, tools: list[ToolDefinition]) -> AgentDecision:
        self.calls += 1
        if self.calls == 1:
            assert "recall_memory" in {item.name for item in tools}
            assert '"current_revision_memories": 1' in context
            assert "create_app 在 main.py 中创建应用" not in context
            return AgentDecision(
                rationale="已有当前版本入口记忆，先主动召回并检查 Evidence。",
                action=ToolAction(
                    tool_name="recall_memory",
                    arguments={"memory_types": ["entry_point"]},
                ),
            )
        assert tools == []
        observation_id = re.findall(r'"id": "(obs_[a-f0-9]+)"', context)[-1]
        return AgentDecision(
            rationale="当前 Commit 的已验证记忆足以回答入口问题。",
            action=FinishAction(
                analysis=AgentAnalysisResult(
                    project_summary="一个带持久化入口记忆的示例仓库。",
                    entrypoints=[
                        AgentFinding(
                            claim="main.py 中的 create_app 创建应用入口。",
                            confidence="confirmed",
                            evidence_ids=["ev_recalled"],
                        )
                    ],
                    evidence=[
                        AgentEvidence(
                            evidence_id="ev_recalled",
                            claim="当前 Revision Memory 保存了入口源码证据。",
                            path="src/sample_service/main.py",
                            start_line=2,
                            end_line=4,
                            observation_id=observation_id,
                            source_kind="memory",
                            resolution="not_applicable",
                        )
                    ],
                    limitations=["只回答入口问题。"],
                )
            ),
        )


class SearchThenReadThenFinishModel:
    """Proves that an empty memory result sends control back to code exploration."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, context: str, tools: list[ToolDefinition]) -> AgentDecision:
        del tools
        self.calls += 1
        if self.calls == 1:
            return AgentDecision(
                rationale="Check whether a prior entrypoint finding exists.",
                action=ToolAction(
                    tool_name="search_memory",
                    arguments={"query": "create_app entrypoint"},
                ),
            )
        if self.calls == 2:
            assert '"total_matches": 0' in context
            return AgentDecision(
                rationale="Memory is insufficient, so inspect the source file.",
                action=ToolAction(
                    tool_name="read_file",
                    arguments={
                        "path": "src/sample_service/main.py",
                        "start_line": 1,
                        "end_line": 8,
                    },
                ),
            )
        observation_id = re.findall(r'"id": "(obs_[a-f0-9]+)"', context)[-1]
        return AgentDecision(
            rationale="The source observation now provides direct evidence.",
            action=FinishAction(
                analysis=AgentAnalysisResult(
                    project_summary="A sample Python service.",
                    entrypoints=[
                        AgentFinding(
                            claim="The application entrypoint is in main.py.",
                            confidence="confirmed",
                            evidence_ids=["ev_read"],
                        )
                    ],
                    evidence=[
                        AgentEvidence(
                            evidence_id="ev_read",
                            claim="The source file defines the application entrypoint.",
                            path="src/sample_service/main.py",
                            start_line=1,
                            end_line=5,
                            observation_id=observation_id,
                            source_kind="read",
                            resolution="not_applicable",
                        )
                    ],
                    limitations=["Only the entrypoint file was inspected."],
                )
            ),
        )


def test_agent_autonomously_recalls_memory_without_automatic_context_injection(
    tmp_path: Path,
    fixture_repository: Path,
) -> None:
    settings = Settings(
        memory_database=tmp_path / "memory.db",
        agent_max_iterations=4,
        agent_max_tool_calls=3,
    )
    store = SqliteMemoryStore(MemoryDatabase(settings.memory_database))
    source = RepositorySource(
        original_url="https://github.com/example/sample-service",
        normalized_url="https://github.com/example/sample-service",
        owner="example",
        name="sample-service",
        clone_url="https://github.com/example/sample-service.git",
    )
    repository = store.get_or_create_repository(source)
    revision = store.get_or_create_revision(repository.id, "abc123")
    store.save_memory(
        repository.id,
        revision.id,
        "abc123",
        "historical_run",
        MemoryCandidate(
            memory_type="entry_point",
            title="create_app 是应用入口",
            content="create_app 在 main.py 中创建应用。",
            tags=["入口", "entry"],
            symbol_names=["create_app"],
            paths=["src/sample_service/main.py"],
            confidence="confirmed",
            evidence=[
                MemoryEvidence(
                    evidence_id="ev_original",
                    observation_id="obs_original",
                    source_kind="read",
                    resolution="not_applicable",
                    path="src/sample_service/main.py",
                    start_line=2,
                    end_line=4,
                    verified=True,
                )
            ],
        ),
    )
    reader = RepositoryReader(settings)
    snapshot = RepositoryScanner(settings, reader).scan(
        fixture_repository,
        source,
        "abc123",
    )
    state = AgentState(
        goal="入口在哪里？",
        repository_url=source.normalized_url,
        commit_sha="abc123",
        bootstrap_summary="fixture",
        memory_catalog=store.memory_catalog(repository.id, revision.id),
    )
    runtime = AgentRuntime(
        settings,
        RecallThenFinishModel(),
        build_default_registry(settings),
        AgentContextBuilder(settings),
    )
    context = build_tool_context(
        settings,
        fixture_repository,
        snapshot,
        reader,
        memory_store=store,
        memory_repository_id=repository.id,
        memory_revision_id=revision.id,
        memory_run_id=state.run_id,
        memory_catalog=state.memory_catalog,
    )

    result = runtime.run(state, context)

    assert result.state.status == "completed"
    assert result.state.memory_call_count == 1
    assert result.state.memory_results_seen == 1
    assert result.state.memory_entries_cited == 1
    assert result.state.tool_call_count == 1
    assert result.trace.memory_entries_recalled == 1
    assert result.trace.memory_entries_cited == 1
    assert result.trace.steps[0].observation.tool_name == "recall_memory"  # type: ignore[union-attr]
    assert result.state.final_analysis.evidence[0].verified is True  # type: ignore[union-attr]
    with store.database.connect() as connection:
        usage_types = {
            str(row["usage_type"])
            for row in connection.execute(
                "SELECT usage_type FROM memory_usage WHERE run_id = ?",
                (state.run_id,),
            ).fetchall()
        }
    assert usage_types == {"recalled", "cited"}


def test_agent_returns_to_code_tools_when_memory_is_insufficient(
    tmp_path: Path,
    fixture_repository: Path,
) -> None:
    settings = Settings(
        memory_database=tmp_path / "memory.db",
        agent_max_iterations=4,
        agent_max_tool_calls=3,
    )
    store = SqliteMemoryStore(MemoryDatabase(settings.memory_database))
    source = RepositorySource(
        original_url="https://github.com/example/sample-service",
        normalized_url="https://github.com/example/sample-service",
        owner="example",
        name="sample-service",
        clone_url="https://github.com/example/sample-service.git",
    )
    repository = store.get_or_create_repository(source)
    revision = store.get_or_create_revision(repository.id, "abc123")
    reader = RepositoryReader(settings)
    snapshot = RepositoryScanner(settings, reader).scan(
        fixture_repository,
        source,
        "abc123",
    )
    state = AgentState(
        goal="Find the application entrypoint.",
        repository_url=source.normalized_url,
        commit_sha="abc123",
        bootstrap_summary="fixture",
        memory_catalog=store.memory_catalog(repository.id, revision.id),
    )
    runtime = AgentRuntime(
        settings,
        SearchThenReadThenFinishModel(),
        build_default_registry(settings),
        AgentContextBuilder(settings),
    )
    context = build_tool_context(
        settings,
        fixture_repository,
        snapshot,
        reader,
        memory_store=store,
        memory_repository_id=repository.id,
        memory_revision_id=revision.id,
        memory_run_id=state.run_id,
        memory_catalog=state.memory_catalog,
    )

    result = runtime.run(state, context)

    assert result.state.status == "completed"
    assert result.state.memory_call_count == 1
    assert result.state.memory_results_seen == 0
    assert [step.observation.tool_name for step in result.trace.steps[:2]] == [  # type: ignore[union-attr]
        "search_memory",
        "read_file",
    ]
    assert result.state.final_analysis.evidence[0].source_kind == "read"  # type: ignore[union-attr]
