"""SQLite connection management and versioned schema creation."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path


class MemoryDatabaseError(RuntimeError):
    """Raised when the repository memory database cannot be used safely."""


class MemoryDatabase:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path, *, enable_fts: bool = True) -> None:
        self.path = path
        self.enable_fts = enable_fts
        self.fts_enabled = False

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.connect() as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version > self.SCHEMA_VERSION:
                    raise MemoryDatabaseError(
                        f"Memory schema version {version} is newer than supported "
                        f"version {self.SCHEMA_VERSION}."
                    )
                if version == 0:
                    self._create_schema(connection)
                self.fts_enabled = self.enable_fts and self._detect_fts(connection)
        except sqlite3.Error as exc:
            raise MemoryDatabaseError(f"Could not initialize memory database: {exc}") from exc

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _detect_fts(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memory_fts'"
        ).fetchone()
        return row is not None

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            BEGIN IMMEDIATE;

            CREATE TABLE repositories (
                id TEXT PRIMARY KEY,
                normalized_url TEXT NOT NULL UNIQUE,
                owner TEXT NOT NULL,
                name TEXT NOT NULL,
                default_branch TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE revisions (
                id TEXT PRIMARY KEY,
                repository_id TEXT NOT NULL REFERENCES repositories(id),
                commit_sha TEXT NOT NULL,
                source_branch TEXT,
                tree_fingerprint TEXT,
                detected_stack TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                UNIQUE(repository_id, commit_sha)
            );

            CREATE TABLE analysis_runs (
                id TEXT PRIMARY KEY,
                revision_id TEXT NOT NULL REFERENCES revisions(id),
                goal TEXT NOT NULL,
                final_status TEXT NOT NULL,
                model_name TEXT,
                llm_request_count INTEGER NOT NULL DEFAULT 0,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                tool_call_count INTEGER NOT NULL DEFAULT 0,
                report_path TEXT,
                trace_path TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT
            );

            CREATE TABLE memory_entries (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                repository_id TEXT NOT NULL REFERENCES repositories(id),
                revision_id TEXT NOT NULL REFERENCES revisions(id),
                source_run_id TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                symbol_names_json TEXT NOT NULL,
                paths_json TEXT NOT NULL,
                confidence TEXT NOT NULL,
                status TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                coverage_json TEXT NOT NULL,
                memory_schema_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(revision_id, memory_type, content_hash)
            );

            CREATE TABLE evidence (
                id TEXT NOT NULL,
                memory_id TEXT NOT NULL REFERENCES memory_entries(id) ON DELETE CASCADE,
                revision_id TEXT NOT NULL REFERENCES revisions(id),
                observation_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                resolution TEXT NOT NULL,
                path TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                start_col INTEGER NOT NULL DEFAULT 0,
                end_line INTEGER NOT NULL,
                end_col INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT,
                verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY(memory_id, id)
            );

            CREATE TABLE exploration_episodes (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                revision_id TEXT NOT NULL REFERENCES revisions(id),
                goal TEXT NOT NULL,
                explored_paths_json TEXT NOT NULL,
                tools_used_json TEXT NOT NULL,
                confirmed_summary TEXT NOT NULL,
                rejected_hypotheses_json TEXT NOT NULL,
                unresolved_questions_json TEXT NOT NULL,
                coverage_notes_json TEXT NOT NULL,
                stop_reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                repository_id TEXT NOT NULL REFERENCES repositories(id),
                revision_id TEXT NOT NULL REFERENCES revisions(id),
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                summarized_through_sequence INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                answer_status TEXT,
                source_run_id TEXT,
                evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                token_usage_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(conversation_id, sequence)
            );

            CREATE TABLE memory_usage (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                memory_id TEXT NOT NULL REFERENCES memory_entries(id),
                observation_id TEXT NOT NULL,
                usage_type TEXT NOT NULL,
                query TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX idx_revisions_repository ON revisions(repository_id, created_at);
            CREATE INDEX idx_runs_revision ON analysis_runs(revision_id, started_at);
            CREATE INDEX idx_memory_scope
                ON memory_entries(repository_id, revision_id, status, memory_type);
            CREATE INDEX idx_evidence_location ON evidence(revision_id, path, start_line);
            CREATE INDEX idx_messages_conversation ON messages(conversation_id, sequence);

            PRAGMA user_version = 1;
            COMMIT;
            """
        )
        if not self.enable_fts:
            return
        with suppress(sqlite3.OperationalError):
            connection.execute(
                """
                CREATE VIRTUAL TABLE memory_fts USING fts5(
                    memory_id UNINDEXED,
                    title,
                    content,
                    tags,
                    symbol_names,
                    paths,
                    tokenize='unicode61'
                )
                """
            )
