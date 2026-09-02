"""Shared secret redaction for persisted memory and conversation text."""

from __future__ import annotations

import re
from collections.abc import Iterable

_SECRET_PATTERN = re.compile(r"\b(?:sk|api)[-_][A-Za-z0-9_-]{12,}\b", re.IGNORECASE)


def contains_possible_secret(text: str) -> bool:
    return _SECRET_PATTERN.search(text) is not None


def redact_memory_text(text: str, secrets: Iterable[str] = ()) -> str:
    safe = text
    for secret in secrets:
        if secret:
            safe = safe.replace(secret, "[REDACTED]")
    return _SECRET_PATTERN.sub("[REDACTED]", safe)
