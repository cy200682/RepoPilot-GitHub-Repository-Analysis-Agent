"""Safe and bounded repository file reading."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Protocol

from repopilot.config import Settings
from repopilot.exceptions import RepositoryReadError
from repopilot.models.repository import ReadFileResult


class RepositoryReaderProtocol(Protocol):
    """Capability boundary used by Scanner, Context Builder, and future Tools."""

    def read_file(
        self,
        root_path: Path,
        relative_path: str,
        *,
        max_bytes: int | None = None,
    ) -> ReadFileResult: ...

    def is_text_file(self, root_path: Path, relative_path: str) -> bool: ...

    def is_link_or_junction(self, path: Path) -> bool: ...


class RepositoryReader:
    """Read repository-relative text without escaping the repository root."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def read_file(
        self,
        root_path: Path,
        relative_path: str,
        *,
        max_bytes: int | None = None,
    ) -> ReadFileResult:
        _, path, normalized = self._resolve_safe_path(root_path, relative_path)
        if self.is_link_or_junction(path):
            raise RepositoryReadError(f"Refusing to read linked path: {normalized}")
        if not path.is_file():
            raise RepositoryReadError(f"Repository file does not exist: {normalized}")

        limit = self.settings.max_file_bytes
        if max_bytes is not None:
            if max_bytes <= 0:
                raise RepositoryReadError("max_bytes must be greater than zero.")
            limit = min(limit, max_bytes)

        try:
            size = path.stat().st_size
            data = path.read_bytes()[: limit + 1]
        except OSError as exc:
            raise RepositoryReadError(f"Could not read {normalized}: {exc}") from exc
        if b"\x00" in data[:8192]:
            raise RepositoryReadError(f"Binary files are not readable as text: {normalized}")

        truncated = len(data) > limit or size > limit
        selected = data[:limit]
        return ReadFileResult(
            relative_path=normalized,
            content=selected.decode("utf-8", errors="replace"),
            size_bytes=size,
            bytes_read=len(selected),
            truncated=truncated,
        )

    def is_text_file(self, root_path: Path, relative_path: str) -> bool:
        try:
            _, path, _ = self._resolve_safe_path(root_path, relative_path)
            if self.is_link_or_junction(path) or not path.is_file():
                return False
            sample = path.read_bytes()[:8192]
        except (OSError, RepositoryReadError):
            return False
        return b"\x00" not in sample

    @staticmethod
    def is_link_or_junction(path: Path) -> bool:
        is_junction = getattr(path, "is_junction", lambda: False)
        return path.is_symlink() or bool(is_junction())

    @staticmethod
    def _resolve_safe_path(root_path: Path, relative_path: str) -> tuple[Path, Path, str]:
        root = root_path.resolve()
        normalized_path = PurePosixPath(relative_path.replace("\\", "/"))
        if normalized_path.is_absolute() or ".." in normalized_path.parts:
            raise RepositoryReadError("File path must stay inside the repository root.")
        normalized = normalized_path.as_posix()
        if normalized in {"", "."}:
            raise RepositoryReadError("A repository-relative file path is required.")
        path = (root / Path(*normalized_path.parts)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise RepositoryReadError("File path escapes the repository root.") from exc
        return root, path, normalized
