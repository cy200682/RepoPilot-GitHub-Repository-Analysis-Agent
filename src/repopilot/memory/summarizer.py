"""Deterministic bounded summaries for older conversation messages."""

from __future__ import annotations

from repopilot.memory.models import MessageRecord


class ConversationSummarizer:
    def __init__(self, max_chars: int = 8_000) -> None:
        self.max_chars = max_chars

    def summarize(self, previous: str, messages: list[MessageRecord]) -> str:
        lines = [previous.strip()] if previous.strip() else []
        for message in messages:
            content = " ".join(message.content.split())
            if len(content) > 500:
                content = content[:500] + "…"
            evidence = (
                " evidence=" + ",".join(message.evidence_ids[:8]) if message.evidence_ids else ""
            )
            lines.append(f"[{message.sequence}:{message.role}] {content}{evidence}")
        result = "\n".join(lines)
        if len(result) <= self.max_chars:
            return result
        return "[older conversation summary truncated]\n" + result[-self.max_chars :]
