"""SQLite and in-memory adapters for evidence-grounded repository memory."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from repopilot.agent.state import AgentState
from repopilot.memory.database import MemoryDatabase
from repopilot.memory.models import (
    ConversationRecord,
    ExplorationEpisode,
    MemoryCandidate,
    MemoryEntry,
    MemoryEvidence,
    MemoryStats,
    MemoryStatus,
    MessageRecord,
    RepositoryRecord,
    RevisionRecord,
    memory_id,
    utc_now,
)
from repopilot.models.repository import RepositorySource


class MemoryStore(Protocol):
    fts_enabled: bool

    def get_or_create_repository(self, source: RepositorySource) -> RepositoryRecord: ...

    def get_or_create_revision(
        self,
        repository_id: str,
        commit_sha: str,
        *,
        detected_stack: Sequence[str] = (),
    ) -> RevisionRecord: ...

    def save_memory(
        self,
        repository_id: str,
        revision_id: str,
        commit_sha: str,
        source_run_id: str,
        candidate: MemoryCandidate,
        *,
        status: MemoryStatus = "current",
    ) -> MemoryEntry: ...

    def recall_memories(
        self,
        repository_id: str,
        revision_id: str,
        *,
        memory_types: Sequence[str] = (),
        statuses: Sequence[str] = ("current", "reusable"),
        paths: Sequence[str] = (),
        symbols: Sequence[str] = (),
        limit: int = 10,
    ) -> list[MemoryEntry]: ...

    def search_memories(
        self,
        repository_id: str,
        revision_id: str,
        query: str,
        *,
        memory_types: Sequence[str] = (),
        include_historical: bool = False,
        limit: int = 10,
    ) -> list[MemoryEntry]: ...

    def record_memory_usage(
        self,
        run_id: str,
        memory_id_value: str,
        observation_id: str,
        usage_type: str,
        query: str | None = None,
    ) -> None: ...


class SqliteMemoryStore:
    """Small synchronous store intended for the single-process CLI runtime."""

    def __init__(self, database: MemoryDatabase) -> None:
        self.database = database
        self.database.initialize()

    @property
    def fts_enabled(self) -> bool:
        return self.database.fts_enabled

    def get_or_create_repository(self, source: RepositorySource) -> RepositoryRecord:
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM repositories WHERE normalized_url = ?",
                (source.normalized_url,),
            ).fetchone()
            if row is None:
                identifier = memory_id("repo")
                connection.execute(
                    """
                    INSERT INTO repositories(
                        id, normalized_url, owner, name, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (identifier, source.normalized_url, source.owner, source.name, now, now),
                )
                row = connection.execute(
                    "SELECT * FROM repositories WHERE id = ?", (identifier,)
                ).fetchone()
        assert row is not None
        return self._repository_from_row(row)

    def get_repository(self, repository_id: str) -> RepositoryRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM repositories WHERE id = ?", (repository_id,)
            ).fetchone()
        return self._repository_from_row(row) if row else None

    def get_repository_by_url(self, normalized_url: str) -> RepositoryRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM repositories WHERE normalized_url = ?", (normalized_url,)
            ).fetchone()
        return self._repository_from_row(row) if row else None

    def get_or_create_revision(
        self,
        repository_id: str,
        commit_sha: str,
        *,
        detected_stack: Sequence[str] = (),
    ) -> RevisionRecord:
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM revisions WHERE repository_id = ? AND commit_sha = ?",
                (repository_id, commit_sha),
            ).fetchone()
            if row is None:
                identifier = memory_id("rev")
                connection.execute(
                    """
                    INSERT INTO revisions(
                        id, repository_id, commit_sha, detected_stack, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        identifier,
                        repository_id,
                        commit_sha,
                        self._json(list(detected_stack)),
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM revisions WHERE id = ?", (identifier,)
                ).fetchone()
        assert row is not None
        return self._revision_from_row(row)

    def get_revision(self, revision_id: str) -> RevisionRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM revisions WHERE id = ?", (revision_id,)
            ).fetchone()
        return self._revision_from_row(row) if row else None

    def save_analysis_run(
        self,
        revision_id: str,
        state: AgentState,
        *,
        model_name: str | None,
        report_path: str | None,
        trace_path: str | None,
        started_at: datetime,
        ended_at: datetime | None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO analysis_runs(
                    id, revision_id, goal, final_status, model_name,
                    llm_request_count, prompt_tokens, completion_tokens, total_tokens,
                    tool_call_count, report_path, trace_path, started_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.run_id,
                    revision_id,
                    state.goal,
                    state.status,
                    model_name,
                    state.llm_request_count,
                    state.prompt_tokens,
                    state.completion_tokens,
                    state.total_tokens,
                    state.tool_call_count,
                    report_path,
                    trace_path,
                    started_at.isoformat(),
                    ended_at.isoformat() if ended_at else None,
                ),
            )

    def save_memory(
        self,
        repository_id: str,
        revision_id: str,
        commit_sha: str,
        source_run_id: str,
        candidate: MemoryCandidate,
        *,
        status: MemoryStatus = "current",
    ) -> MemoryEntry:
        content_hash = self._candidate_hash(candidate)
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            existing = connection.execute(
                """
                SELECT id FROM memory_entries
                WHERE revision_id = ? AND memory_type = ? AND content_hash = ?
                """,
                (revision_id, candidate.memory_type, content_hash),
            ).fetchone()
            if existing:
                entry = self._get_memory(connection, str(existing["id"]), match_kind="deduplicated")
                assert entry is not None
                return entry

            identifier = memory_id("mem")
            connection.execute(
                """
                INSERT INTO memory_entries(
                    id, repository_id, revision_id, source_run_id, memory_type,
                    title, content, tags_json, symbol_names_json, paths_json,
                    confidence, status, content_hash, coverage_json,
                    memory_schema_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    identifier,
                    repository_id,
                    revision_id,
                    source_run_id,
                    candidate.memory_type,
                    candidate.title,
                    candidate.content,
                    self._json(self._normalize_terms(candidate.tags)),
                    self._json(self._normalize_terms(candidate.symbol_names)),
                    self._json(self._normalize_terms(candidate.paths)),
                    candidate.confidence,
                    status,
                    content_hash,
                    self._json(candidate.coverage_notes),
                    now,
                    now,
                ),
            )
            for evidence in candidate.evidence:
                connection.execute(
                    """
                    INSERT INTO evidence(
                        id, memory_id, revision_id, observation_id, source_kind,
                        resolution, path, start_line, start_col, end_line, end_col,
                        content_hash, verified, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence.evidence_id,
                        identifier,
                        revision_id,
                        evidence.observation_id,
                        evidence.source_kind,
                        evidence.resolution,
                        evidence.path,
                        evidence.start_line,
                        evidence.start_col,
                        evidence.end_line,
                        evidence.end_col,
                        evidence.content_hash,
                        int(evidence.verified),
                        now,
                    ),
                )
            if self.fts_enabled:
                connection.execute(
                    """
                    INSERT INTO memory_fts(
                        memory_id, title, content, tags, symbol_names, paths
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identifier,
                        candidate.title,
                        candidate.content,
                        " ".join(candidate.tags),
                        " ".join(candidate.symbol_names),
                        " ".join(candidate.paths),
                    ),
                )
            entry = self._get_memory(connection, identifier)
        assert entry is not None
        entry.commit_sha = commit_sha
        return entry

    def get_memory(self, memory_id_value: str) -> MemoryEntry | None:
        with self.database.connect() as connection:
            return self._get_memory(connection, memory_id_value)

    def recall_memories(
        self,
        repository_id: str,
        revision_id: str,
        *,
        memory_types: Sequence[str] = (),
        statuses: Sequence[str] = ("current", "reusable"),
        paths: Sequence[str] = (),
        symbols: Sequence[str] = (),
        limit: int = 10,
    ) -> list[MemoryEntry]:
        clauses = ["repository_id = ?", "revision_id = ?"]
        parameters: list[object] = [repository_id, revision_id]
        self._add_in_filter(clauses, parameters, "memory_type", memory_types)
        self._add_in_filter(clauses, parameters, "status", statuses)
        sql = "SELECT id FROM memory_entries WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        parameters.append(max(limit * 4, limit))
        with self.database.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
            entries = [
                item
                for row in rows
                if (item := self._get_memory(connection, str(row["id"]), "structured"))
            ]
        normalized_paths = {item.casefold() for item in paths}
        normalized_symbols = {item.casefold() for item in symbols}
        if normalized_paths:
            entries = [
                entry
                for entry in entries
                if normalized_paths.intersection(item.casefold() for item in entry.paths)
            ]
        if normalized_symbols:
            entries = [
                entry
                for entry in entries
                if normalized_symbols.intersection(item.casefold() for item in entry.symbol_names)
            ]
        return entries[:limit]

    def search_memories(
        self,
        repository_id: str,
        revision_id: str,
        query: str,
        *,
        memory_types: Sequence[str] = (),
        include_historical: bool = False,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        matched: dict[str, tuple[str, float]] = {}
        with self.database.connect() as connection:
            if self.fts_enabled:
                expression = self._fts_expression(query)
                if expression:
                    try:
                        rows = connection.execute(
                            """
                            SELECT memory_id, bm25(memory_fts) AS rank
                            FROM memory_fts WHERE memory_fts MATCH ? LIMIT ?
                            """,
                            (expression, max(limit * 5, limit)),
                        ).fetchall()
                        for row in rows:
                            matched[str(row["memory_id"])] = ("fts5", -float(row["rank"]))
                    except sqlite3.OperationalError:
                        pass

            like = f"%{query[:200]}%"
            rows = connection.execute(
                """
                SELECT id FROM memory_entries
                WHERE title LIKE ? OR content LIKE ? OR tags_json LIKE ?
                   OR symbol_names_json LIKE ? OR paths_json LIKE ?
                LIMIT ?
                """,
                (like, like, like, like, like, max(limit * 5, limit)),
            ).fetchall()
            for row in rows:
                matched.setdefault(str(row["id"]), ("phrase", 1.0))

            entries = []
            for identifier, (kind, score) in matched.items():
                entry = self._get_memory(connection, identifier, kind, score)
                if entry is None or entry.repository_id != repository_id:
                    continue
                if not include_historical and entry.revision_id != revision_id:
                    continue
                if memory_types and entry.memory_type not in memory_types:
                    continue
                entries.append(entry)
        entries.sort(
            key=lambda item: (
                item.revision_id == revision_id,
                item.status == "current",
                item.match_score or 0,
                item.updated_at,
            ),
            reverse=True,
        )
        return entries[:limit]

    def update_memory_status(self, memory_id_value: str, status: MemoryStatus) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE memory_entries SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now().isoformat(), memory_id_value),
            )

    def save_exploration_episode(self, episode: ExplorationEpisode) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO exploration_episodes(
                    id, run_id, revision_id, goal, explored_paths_json, tools_used_json,
                    confirmed_summary, rejected_hypotheses_json, unresolved_questions_json,
                    coverage_notes_json, stop_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode.id,
                    episode.run_id,
                    episode.revision_id,
                    episode.goal,
                    self._json(episode.explored_paths),
                    self._json(episode.tools_used),
                    episode.confirmed_summary,
                    self._json(episode.rejected_hypotheses),
                    self._json(episode.unresolved_questions),
                    self._json(episode.coverage_notes),
                    episode.stop_reason,
                    episode.created_at.isoformat(),
                ),
            )

    def create_conversation(
        self,
        repository_id: str,
        revision_id: str,
        title: str,
    ) -> ConversationRecord:
        identifier = memory_id("conv")
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations(
                    id, repository_id, revision_id, title, summary,
                    summarized_through_sequence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, '', 0, ?, ?)
                """,
                (identifier, repository_id, revision_id, title[:300], now, now),
            )
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?", (identifier,)
            ).fetchone()
        assert row is not None
        return self._conversation_from_row(row)

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return self._conversation_from_row(row) if row else None

    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        answer_status: str | None = None,
        source_run_id: str | None = None,
        evidence_ids: Sequence[str] = (),
        token_usage: dict[str, int | bool] | None = None,
    ) -> MessageRecord:
        identifier = memory_id("msg")
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next FROM messages "
                "WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            sequence = int(row["next"])
            connection.execute(
                """
                INSERT INTO messages(
                    id, conversation_id, sequence, role, content, answer_status,
                    source_run_id, evidence_ids_json, token_usage_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    conversation_id,
                    sequence,
                    role,
                    content,
                    answer_status,
                    source_run_id,
                    self._json(list(evidence_ids)),
                    self._json(token_usage or {}),
                    now,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            message = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (identifier,)
            ).fetchone()
        assert message is not None
        return self._message_from_row(message)

    def list_messages(self, conversation_id: str, *, limit: int = 100) -> list[MessageRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM messages WHERE conversation_id = ?
                ORDER BY sequence DESC LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
        return [self._message_from_row(row) for row in reversed(rows)]

    def update_conversation_summary(
        self,
        conversation_id: str,
        summary: str,
        summarized_through_sequence: int,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE conversations
                SET summary = ?, summarized_through_sequence = ?, updated_at = ?
                WHERE id = ?
                """,
                (summary, summarized_through_sequence, utc_now().isoformat(), conversation_id),
            )

    def memory_catalog(self, repository_id: str, revision_id: str) -> dict[str, object]:
        with self.database.connect() as connection:
            current = int(
                connection.execute(
                    "SELECT COUNT(*) FROM memory_entries WHERE repository_id = ? "
                    "AND revision_id = ? AND status IN ('current', 'reusable')",
                    (repository_id, revision_id),
                ).fetchone()[0]
            )
            historical = int(
                connection.execute(
                    "SELECT COUNT(*) FROM memory_entries WHERE repository_id = ? "
                    "AND revision_id != ?",
                    (repository_id, revision_id),
                ).fetchone()[0]
            )
            rows = connection.execute(
                """
                SELECT memory_type, COUNT(*) AS count FROM memory_entries
                WHERE repository_id = ? AND revision_id = ?
                GROUP BY memory_type ORDER BY memory_type
                """,
                (repository_id, revision_id),
            ).fetchall()
        return {
            "current_revision_memories": current,
            "historical_memories": historical,
            "memory_types": {str(row["memory_type"]): int(row["count"]) for row in rows},
            "fts_enabled": self.fts_enabled,
        }

    def list_memories(self, *, limit: int = 50) -> list[MemoryEntry]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM memory_entries ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [
                entry
                for row in rows
                if (entry := self._get_memory(connection, str(row["id"]))) is not None
            ]

    def stats(self) -> MemoryStats:
        tables = {
            "repositories": "repositories",
            "revisions": "revisions",
            "runs": "analysis_runs",
            "memories": "memory_entries",
            "conversations": "conversations",
            "messages": "messages",
        }
        with self.database.connect() as connection:
            counts = {
                key: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for key, table in tables.items()
            }
            types = connection.execute(
                "SELECT memory_type, COUNT(*) AS count FROM memory_entries GROUP BY memory_type"
            ).fetchall()
            statuses = connection.execute(
                "SELECT status, COUNT(*) AS count FROM memory_entries GROUP BY status"
            ).fetchall()
        return MemoryStats(
            **counts,
            by_type={str(row["memory_type"]): int(row["count"]) for row in types},
            by_status={str(row["status"]): int(row["count"]) for row in statuses},
            fts_enabled=self.fts_enabled,
        )

    def record_memory_usage(
        self,
        run_id: str,
        memory_id_value: str,
        observation_id: str,
        usage_type: str,
        query: str | None = None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_usage(
                    id, run_id, memory_id, observation_id, usage_type, query, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id("usage"),
                    run_id,
                    memory_id_value,
                    observation_id,
                    usage_type,
                    query,
                    utc_now().isoformat(),
                ),
            )

    def _get_memory(
        self,
        connection: sqlite3.Connection,
        identifier: str,
        match_kind: str | None = None,
        match_score: float | None = None,
    ) -> MemoryEntry | None:
        row = connection.execute(
            """
            SELECT memory_entries.*, revisions.commit_sha
            FROM memory_entries
            JOIN revisions ON revisions.id = memory_entries.revision_id
            WHERE memory_entries.id = ?
            """,
            (identifier,),
        ).fetchone()
        if row is None:
            return None
        evidence_rows = connection.execute(
            "SELECT * FROM evidence WHERE memory_id = ? ORDER BY path, start_line",
            (identifier,),
        ).fetchall()
        return MemoryEntry.model_validate(
            {
                "id": str(row["id"]),
                "repository_id": str(row["repository_id"]),
                "revision_id": str(row["revision_id"]),
                "source_run_id": str(row["source_run_id"]),
                "commit_sha": str(row["commit_sha"]),
                "memory_type": str(row["memory_type"]),
                "title": str(row["title"]),
                "content": str(row["content"]),
                "tags": self._load_list(row["tags_json"]),
                "symbol_names": self._load_list(row["symbol_names_json"]),
                "paths": self._load_list(row["paths_json"]),
                "confidence": str(row["confidence"]),
                "status": str(row["status"]),
                "content_hash": str(row["content_hash"]),
                "coverage_notes": self._load_list(row["coverage_json"]),
                "evidence": [self._evidence_from_row(item) for item in evidence_rows],
                "created_at": datetime.fromisoformat(str(row["created_at"])),
                "updated_at": datetime.fromisoformat(str(row["updated_at"])),
                "match_kind": match_kind,
                "match_score": match_score,
            }
        )

    @staticmethod
    def _candidate_hash(candidate: MemoryCandidate) -> str:
        payload = {
            "type": candidate.memory_type,
            "title": candidate.title.strip(),
            "content": candidate.content.strip(),
            "evidence": sorted(
                (
                    item.path,
                    item.start_line,
                    item.end_line,
                    item.resolution,
                )
                for item in candidate.evidence
            ),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _fts_expression(query: str) -> str:
        terms = [term.strip().replace('"', '""') for term in query.split() if term.strip()]
        return " OR ".join(f'"{term}"' for term in terms[:12])

    @staticmethod
    def _normalize_terms(values: Sequence[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            key = item.casefold()
            if item and key not in seen:
                seen.add(key)
                result.append(item)
        return result

    @staticmethod
    def _add_in_filter(
        clauses: list[str],
        parameters: list[object],
        column: str,
        values: Sequence[str],
    ) -> None:
        if not values:
            return
        placeholders = ",".join("?" for _ in values)
        clauses.append(f"{column} IN ({placeholders})")
        parameters.extend(values)

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _load_list(value: object) -> list[str]:
        loaded = json.loads(str(value))
        return [str(item) for item in loaded] if isinstance(loaded, list) else []

    @staticmethod
    def _repository_from_row(row: sqlite3.Row) -> RepositoryRecord:
        return RepositoryRecord(
            id=str(row["id"]),
            normalized_url=str(row["normalized_url"]),
            owner=str(row["owner"]),
            name=str(row["name"]),
            default_branch=str(row["default_branch"]) if row["default_branch"] else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _revision_from_row(row: sqlite3.Row) -> RevisionRecord:
        return RevisionRecord(
            id=str(row["id"]),
            repository_id=str(row["repository_id"]),
            commit_sha=str(row["commit_sha"]),
            source_branch=str(row["source_branch"]) if row["source_branch"] else None,
            tree_fingerprint=str(row["tree_fingerprint"]) if row["tree_fingerprint"] else None,
            detected_stack=SqliteMemoryStore._load_list(row["detected_stack"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _evidence_from_row(row: sqlite3.Row) -> MemoryEvidence:
        return MemoryEvidence(
            evidence_id=str(row["id"]),
            observation_id=str(row["observation_id"]),
            source_kind=str(row["source_kind"]),
            resolution=str(row["resolution"]),
            path=str(row["path"]),
            start_line=int(row["start_line"]),
            start_col=int(row["start_col"]),
            end_line=int(row["end_line"]),
            end_col=int(row["end_col"]),
            content_hash=str(row["content_hash"]) if row["content_hash"] else None,
            verified=bool(row["verified"]),
        )

    @staticmethod
    def _conversation_from_row(row: sqlite3.Row) -> ConversationRecord:
        return ConversationRecord(
            id=str(row["id"]),
            repository_id=str(row["repository_id"]),
            revision_id=str(row["revision_id"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            summarized_through_sequence=int(row["summarized_through_sequence"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> MessageRecord:
        usage = json.loads(str(row["token_usage_json"]))
        return MessageRecord.model_validate(
            {
                "id": str(row["id"]),
                "conversation_id": str(row["conversation_id"]),
                "sequence": int(row["sequence"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                "answer_status": (str(row["answer_status"]) if row["answer_status"] else None),
                "source_run_id": (str(row["source_run_id"]) if row["source_run_id"] else None),
                "evidence_ids": SqliteMemoryStore._load_list(row["evidence_ids_json"]),
                "token_usage": usage if isinstance(usage, dict) else {},
                "created_at": datetime.fromisoformat(str(row["created_at"])),
            }
        )
