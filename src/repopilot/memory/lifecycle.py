"""Commit-aware freshness classification for recalled memories."""

from __future__ import annotations

from collections.abc import Mapping

from repopilot.memory.models import MemoryEntry, MemoryStatus


def classify_memory(
    entry: MemoryEntry,
    current_revision_id: str,
    current_file_hashes: Mapping[str, str] | None = None,
) -> MemoryStatus:
    if entry.status in {"invalid", "superseded"}:
        return entry.status
    if entry.revision_id == current_revision_id:
        return "current"
    if current_file_hashes is None:
        return "stale"
    if not entry.evidence:
        return "needs_review"
    for evidence in entry.evidence:
        current = current_file_hashes.get(evidence.path)
        if current is None:
            return "invalid"
        if evidence.content_hash is None or evidence.content_hash != current:
            return "stale"
    return "reusable"
