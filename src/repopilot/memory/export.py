"""Validated JSON export and merge import for repository memory."""

from __future__ import annotations

import json
from pathlib import Path

from repopilot.memory.repository import SqliteMemoryStore
from repopilot.memory.safety import contains_possible_secret


class MemoryExportError(RuntimeError):
    pass


class MemoryExporter:
    EXPORT_VERSION = 1
    MAX_IMPORT_BYTES = 20_000_000
    TABLES = (
        "repositories",
        "revisions",
        "analysis_runs",
        "memory_entries",
        "evidence",
        "exploration_episodes",
        "conversations",
        "messages",
        "memory_usage",
    )

    def export_file(self, store: SqliteMemoryStore, output: Path) -> None:
        tables: dict[str, list[dict[str, object]]] = {}
        with store.database.connect() as connection:
            for table in self.TABLES:
                rows = connection.execute(f"SELECT * FROM {table}").fetchall()
                values = [dict(row) for row in rows]
                if table == "memory_entries":
                    for value in values:
                        value.pop("rowid", None)
                tables[table] = values
        payload = {
            "export_version": self.EXPORT_VERSION,
            "memory_schema_version": store.database.SCHEMA_VERSION,
            "tables": tables,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        self._reject_secrets(text)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(output)

    def import_file(self, store: SqliteMemoryStore, source: Path) -> dict[str, int]:
        if not source.is_file():
            raise MemoryExportError(f"Memory export does not exist: {source}")
        if source.stat().st_size > self.MAX_IMPORT_BYTES:
            raise MemoryExportError("Memory export exceeds the 20 MB import limit.")
        text = source.read_text(encoding="utf-8")
        self._reject_secrets(text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MemoryExportError(f"Memory export is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("export_version") != self.EXPORT_VERSION:
            raise MemoryExportError("Unsupported memory export version.")
        if payload.get("memory_schema_version") != store.database.SCHEMA_VERSION:
            raise MemoryExportError("Memory export schema version is incompatible.")
        tables = payload.get("tables")
        if not isinstance(tables, dict) or set(tables) - set(self.TABLES):
            raise MemoryExportError("Memory export contains unknown tables.")

        imported: dict[str, int] = {}
        with store.database.connect() as connection:
            for table in self.TABLES:
                rows = tables.get(table, [])
                if not isinstance(rows, list):
                    raise MemoryExportError(f"Table {table} must be a list.")
                allowed = {
                    str(row["name"])
                    for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                }
                count = 0
                for value in rows:
                    if not isinstance(value, dict) or not value or set(value) - allowed:
                        raise MemoryExportError(f"Table {table} contains invalid columns.")
                    columns = list(value)
                    placeholders = ",".join("?" for _ in columns)
                    names = ",".join(columns)
                    cursor = connection.execute(
                        f"INSERT OR IGNORE INTO {table} ({names}) VALUES ({placeholders})",
                        [value[column] for column in columns],
                    )
                    count += max(cursor.rowcount, 0)
                imported[table] = count
            if store.fts_enabled:
                connection.execute("DELETE FROM memory_fts")
                connection.execute(
                    """
                    INSERT INTO memory_fts(memory_id, title, content, tags, symbol_names, paths)
                    SELECT id, title, content, tags_json, symbol_names_json, paths_json
                    FROM memory_entries
                    """
                )
        return imported

    @staticmethod
    def _reject_secrets(text: str) -> None:
        if contains_possible_secret(text):
            raise MemoryExportError("Memory export contains a possible API secret.")
