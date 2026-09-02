import sqlite3
from contextlib import closing
from pathlib import Path

from repopilot.agent.actions import AgentAnalysisResult, AgentEvidence, AgentFinding
from repopilot.agent.context import AgentContextBuilder
from repopilot.agent.finish import FinishGate
from repopilot.agent.state import AgentState, EvidenceLocation, Observation
from repopilot.config import Settings
from repopilot.memory.database import MemoryDatabase, MemoryDatabaseError
from repopilot.memory.export import MemoryExporter, MemoryExportError
from repopilot.memory.lifecycle import classify_memory
from repopilot.memory.models import MemoryCandidate, MemoryEvidence
from repopilot.memory.repository import SqliteMemoryStore
from repopilot.memory.safety import contains_possible_secret, redact_memory_text
from repopilot.memory.summarizer import ConversationSummarizer
from repopilot.memory.validation import MemoryValidator
from repopilot.models.repository import RepositorySource
from repopilot.tools.base import ToolContext
from repopilot.tools.memory import (
    RecallMemoryTool,
    SaveMemoryInput,
    SaveMemoryTool,
    SearchMemoryTool,
)


def build_store(tmp_path: Path) -> SqliteMemoryStore:
    return SqliteMemoryStore(MemoryDatabase(tmp_path / "memory.db"))


def source() -> RepositorySource:
    return RepositorySource(
        original_url="https://github.com/example/project",
        normalized_url="https://github.com/example/project",
        owner="example",
        name="project",
        clone_url="https://github.com/example/project.git",
    )


def candidate() -> MemoryCandidate:
    return MemoryCandidate(
        memory_type="entry_point",
        title="main.py 创建应用入口",
        content="create_app 在 main.py 中创建应用。",
        tags=["入口", "entry", "application"],
        symbol_names=["create_app"],
        paths=["src/project/main.py"],
        confidence="confirmed",
        evidence=[
            MemoryEvidence(
                evidence_id="ev_entry",
                observation_id="obs_original",
                source_kind="read",
                resolution="not_applicable",
                path="src/project/main.py",
                start_line=2,
                end_line=4,
                verified=True,
            )
        ],
    )


def test_sqlite_memory_persists_deduplicates_and_searches(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    repository = store.get_or_create_repository(source())
    assert store.get_or_create_repository(source()).id == repository.id
    revision = store.get_or_create_revision(repository.id, "a" * 40)
    assert store.get_or_create_revision(repository.id, "a" * 40).id == revision.id

    first = store.save_memory(repository.id, revision.id, "a" * 40, "run_1", candidate())
    duplicate = store.save_memory(repository.id, revision.id, "a" * 40, "run_2", candidate())

    assert duplicate.id == first.id
    assert store.fts_enabled is True
    assert store.recall_memories(repository.id, revision.id)[0].title == first.title
    assert store.search_memories(repository.id, revision.id, "入口")[0].id == first.id
    assert store.search_memories(repository.id, revision.id, "create_app")[0].id == first.id
    stats = store.stats()
    assert stats.repositories == 1
    assert stats.revisions == 1
    assert stats.memories == 1


def test_memory_database_supports_no_fts_fallback_and_rejects_newer_schema(
    tmp_path: Path,
) -> None:
    database = MemoryDatabase(tmp_path / "plain.db", enable_fts=False)
    store = SqliteMemoryStore(database)
    repository = store.get_or_create_repository(source())
    revision = store.get_or_create_revision(repository.id, "a" * 40)
    store.save_memory(repository.id, revision.id, "a" * 40, "run", candidate())

    assert store.fts_enabled is False
    assert store.search_memories(repository.id, revision.id, "入口")

    newer_path = tmp_path / "newer.db"
    database = MemoryDatabase(newer_path)
    with database.connect() as connection:
        connection.execute("PRAGMA user_version = 99")
    try:
        database.initialize()
    except MemoryDatabaseError as exc:
        assert "newer than supported" in str(exc)
    else:
        raise AssertionError("A newer memory schema must be rejected.")


def test_schema_creation_failure_rolls_back_partial_tables(tmp_path: Path) -> None:
    class BrokenMemoryDatabase(MemoryDatabase):
        def _create_schema(self, connection: sqlite3.Connection) -> None:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE partial_table (id INTEGER PRIMARY KEY);
                CREATE TABLE partial_table (id INTEGER PRIMARY KEY);
                COMMIT;
                """
            )

    database = BrokenMemoryDatabase(tmp_path / "broken.db")

    try:
        database.initialize()
    except MemoryDatabaseError:
        pass
    else:
        raise AssertionError("Broken schema creation unexpectedly succeeded.")

    with closing(sqlite3.connect(database.path)) as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'partial_table'"
        ).fetchone()
    assert row is None


def test_commit_lifecycle_classifies_reusable_stale_and_deleted_memory(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    repository = store.get_or_create_repository(source())
    old_revision = store.get_or_create_revision(repository.id, "a" * 40)
    new_revision = store.get_or_create_revision(repository.id, "b" * 40)
    value = candidate()
    value.evidence[0].content_hash = "same-hash"
    entry = store.save_memory(
        repository.id,
        old_revision.id,
        "a" * 40,
        "run_1",
        value,
    )

    assert (
        classify_memory(
            entry,
            new_revision.id,
            {"src/project/main.py": "same-hash"},
        )
        == "reusable"
    )
    assert (
        classify_memory(
            entry,
            new_revision.id,
            {"src/project/main.py": "changed"},
        )
        == "stale"
    )
    assert classify_memory(entry, new_revision.id, {}) == "invalid"


def test_conversation_messages_and_deterministic_summary(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    repository = store.get_or_create_repository(source())
    revision = store.get_or_create_revision(repository.id, "b" * 40)
    conversation = store.create_conversation(repository.id, revision.id, "入口在哪里")
    first = store.append_message(conversation.id, "user", "入口在哪里？")
    second = store.append_message(
        conversation.id,
        "assistant",
        "入口位于 main.py。",
        evidence_ids=["ev_entry"],
    )

    messages = store.list_messages(conversation.id)
    summary = ConversationSummarizer(max_chars=1_000).summarize("", messages)

    assert [item.sequence for item in messages] == [1, 2]
    assert first.role == "user"
    assert second.evidence_ids == ["ev_entry"]
    assert "入口在哪里" in summary
    assert "evidence=ev_entry" in summary


def test_memory_validator_reuses_finish_gate_evidence_rules() -> None:
    observation = Observation(
        id="obs_original",
        step_id="step_1",
        tool_name="read_file",
        status="success",
        summary="read",
        evidence_locations=[
            EvidenceLocation(path="src/project/main.py", start_line=1, end_line=10)
        ],
    )
    state = AgentState(
        goal="find entry",
        repository_url=source().normalized_url,
        commit_sha="a" * 40,
        bootstrap_summary="fixture",
        observations=[observation],
    )

    accepted = MemoryValidator().validate(candidate(), state)
    invalid = candidate().model_copy(deep=True)
    invalid.evidence[0].start_line = 99
    invalid.evidence[0].end_line = 99
    rejected = MemoryValidator().validate(invalid, state)

    assert accepted.accepted is True
    assert accepted.candidate.evidence[0].verified is True
    assert rejected.accepted is False
    assert any("matching observed line range" in reason for reason in rejected.reasons)


def test_save_memory_tool_accepts_only_observation_grounded_candidate(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    repository = store.get_or_create_repository(source())
    revision = store.get_or_create_revision(repository.id, "a" * 40)
    state = AgentState(
        goal="remember entry",
        repository_url=source().normalized_url,
        commit_sha="a" * 40,
        bootstrap_summary="fixture",
        observations=[
            Observation(
                id="obs_original",
                step_id="step_read",
                tool_name="read_file",
                status="success",
                summary="read",
                evidence_locations=[
                    EvidenceLocation(
                        path="src/project/main.py",
                        start_line=1,
                        end_line=10,
                    )
                ],
            )
        ],
    )
    context = ToolContext.model_construct(
        root_path=tmp_path,
        snapshot=None,
        reader=None,
        memory_store=store,
        memory_repository_id=repository.id,
        memory_revision_id=revision.id,
        memory_run_id=state.run_id,
        agent_state=state,
    )
    tool = SaveMemoryTool(Settings(memory_database=tmp_path / "memory.db"))

    saved = tool.execute(SaveMemoryInput.model_validate(candidate().model_dump()), context, "save")
    invalid = candidate().model_copy(deep=True)
    invalid.evidence[0].start_line = 99
    invalid.evidence[0].end_line = 99
    rejected = tool.execute(
        SaveMemoryInput.model_validate(invalid.model_dump()),
        context,
        "reject",
    )

    assert saved.status == "success"
    assert saved.data["memory_id"].startswith("mem_")
    assert rejected.status == "error"
    assert store.stats().memories == 1


def test_recalled_current_memory_can_support_finish_but_stale_cannot(
    tmp_path: Path,
) -> None:
    store = build_store(tmp_path)
    repository = store.get_or_create_repository(source())
    current = store.get_or_create_revision(repository.id, "a" * 40)
    newer = store.get_or_create_revision(repository.id, "b" * 40)
    store.save_memory(repository.id, current.id, "a" * 40, "run_1", candidate())
    settings = Settings(memory_database=tmp_path / "memory.db")
    state = AgentState(
        goal="find entry",
        repository_url=source().normalized_url,
        commit_sha="a" * 40,
        bootstrap_summary="fixture",
    )
    context = ToolContext.model_construct(
        root_path=tmp_path,
        snapshot=None,
        reader=None,
        memory_store=store,
        memory_repository_id=repository.id,
        memory_revision_id=current.id,
        memory_run_id=state.run_id,
        agent_state=state,
    )
    recalled = RecallMemoryTool(settings).execute(
        RecallMemoryTool.input_model(), context, "step_recall"
    )
    state.observations.append(recalled)
    analysis = AgentAnalysisResult(
        project_summary="fixture",
        entrypoints=[
            AgentFinding(
                claim="main.py creates the app.",
                confidence="confirmed",
                evidence_ids=["ev_memory"],
            )
        ],
        evidence=[
            AgentEvidence(
                evidence_id="ev_memory",
                claim="recalled current evidence",
                path="src/project/main.py",
                start_line=2,
                end_line=4,
                observation_id=recalled.id,
                source_kind="memory",
                resolution="not_applicable",
            )
        ],
        limitations=["Only the remembered entrypoint was checked."],
    )

    assert FinishGate().validate(analysis, state).accepted is True
    historical_context = context.model_copy(
        update={"memory_revision_id": newer.id, "memory_run_id": "run_new"}
    )
    searched = SearchMemoryTool(settings).execute(
        SearchMemoryTool.input_model(
            query="入口",
            include_historical=True,
        ),
        historical_context,
        "step_search",
    )
    assert searched.data["memories"][0]["status"] == "stale"
    assert (
        classify_memory(store.get_memory(recalled.data["memories"][0]["memory_id"]), newer.id)
        == "stale"
    )  # type: ignore[arg-type]


def test_reusable_memory_requires_explicit_content_hash_verification() -> None:
    memory = {
        "status": "reusable",
        "evidence": [
            {
                "path": "src/project/main.py",
                "start_line": 2,
                "end_line": 4,
                "resolution": "not_applicable",
                "verified": True,
            }
        ],
    }
    observation = Observation(
        step_id="step_search",
        tool_name="search_memory",
        status="success",
        summary="Found one unchanged historical memory.",
        data={"memories": [memory], "content_hash_verified": False},
        evidence_locations=[EvidenceLocation(path="src/project/main.py", start_line=2, end_line=4)],
    )
    state = AgentState(
        goal="find entry",
        repository_url=source().normalized_url,
        commit_sha="b" * 40,
        bootstrap_summary="fixture",
        observations=[observation],
    )
    analysis = AgentAnalysisResult(
        project_summary="fixture",
        entrypoints=[
            AgentFinding(
                claim="main.py creates the app.",
                confidence="confirmed",
                evidence_ids=["ev_memory"],
            )
        ],
        evidence=[
            AgentEvidence(
                evidence_id="ev_memory",
                claim="unchanged historical evidence",
                path="src/project/main.py",
                start_line=2,
                end_line=4,
                observation_id=observation.id,
                source_kind="memory",
                resolution="not_applicable",
            )
        ],
        limitations=["Only the remembered entrypoint was checked."],
    )

    assert FinishGate().validate(analysis, state).accepted is False
    observation.data["content_hash_verified"] = True
    assert FinishGate().validate(analysis, state).accepted is True


def test_context_contains_catalog_but_not_unrecalled_memory_content() -> None:
    settings = Settings(memory_enabled=True)
    state = AgentState(
        goal="find entry",
        repository_url=source().normalized_url,
        commit_sha="a" * 40,
        bootstrap_summary="fixture",
        memory_catalog={"current_revision_memories": 2, "memory_types": {"entry_point": 2}},
    )

    context = AgentContextBuilder(settings).build(state, [])

    assert '"current_revision_memories": 2' in context
    assert "main.py creates the secret app" not in context


def test_memory_secret_redaction_handles_configured_and_key_shaped_values() -> None:
    text = "first sk-memory-secret-12345 second private-token"
    safe = redact_memory_text(text, ["private-token"])

    assert "sk-memory-secret-12345" not in safe
    assert "private-token" not in safe
    assert safe.count("[REDACTED]") == 2
    assert contains_possible_secret(text) is True


def test_memory_export_and_import_are_versioned_and_secret_safe(tmp_path: Path) -> None:
    source_store = build_store(tmp_path / "source")
    repository = source_store.get_or_create_repository(source())
    revision = source_store.get_or_create_revision(repository.id, "a" * 40)
    source_store.save_memory(repository.id, revision.id, "a" * 40, "run_1", candidate())
    export_path = tmp_path / "memory.json"

    MemoryExporter().export_file(source_store, export_path)
    target_store = build_store(tmp_path / "target")
    imported = MemoryExporter().import_file(target_store, export_path)

    assert imported["repositories"] == 1
    assert imported["memory_entries"] == 1
    assert target_store.stats().memories == 1
    assert target_store.search_memories(repository.id, revision.id, "入口")

    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text('{"api_key":"sk-this-is-not-safe-12345"}', encoding="utf-8")
    try:
        MemoryExporter().import_file(target_store, unsafe)
    except MemoryExportError as exc:
        assert "secret" in str(exc)
    else:
        raise AssertionError("Unsafe memory import should have been rejected.")
