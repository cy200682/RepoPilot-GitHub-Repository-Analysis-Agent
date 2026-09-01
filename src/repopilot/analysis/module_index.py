"""Path-to-module candidates derived without reading repository source."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from repopilot.models.repository import RepositorySnapshot


class ModuleIndex:
    def __init__(self, snapshot: RepositorySnapshot) -> None:
        self.python_paths = {
            item.relative_path for item in snapshot.files if item.relative_path.endswith(".py")
        }
        self.path_to_candidates: dict[str, list[str]] = {}
        self.module_to_paths: dict[str, list[str]] = {}
        for path in sorted(self.python_paths):
            candidates = self._candidates(path)
            self.path_to_candidates[path] = candidates
            for candidate in candidates:
                self.module_to_paths.setdefault(candidate, []).append(path)

    def module_for_path(self, path: str) -> str:
        candidates = self.path_to_candidates.get(path, [])
        return candidates[0] if candidates else self._module_name(PurePosixPath(path).parts)

    def resolve_module(
        self, module_name: str
    ) -> tuple[str | None, Literal["resolved", "ambiguous", "external"]]:
        paths = self.module_to_paths.get(module_name, [])
        if len(paths) == 1:
            return paths[0], "resolved"
        if len(paths) > 1:
            return None, "ambiguous"
        return None, "external"

    @staticmethod
    def _module_name(parts: tuple[str, ...]) -> str:
        cleaned = list(parts)
        if cleaned and cleaned[-1].endswith(".py"):
            cleaned[-1] = cleaned[-1][:-3]
        if cleaned and cleaned[-1] == "__init__":
            cleaned.pop()
        return ".".join(cleaned)

    def _candidates(self, path: str) -> list[str]:
        parts = PurePosixPath(path).parts
        candidates: list[str] = []
        if parts and parts[0] == "src" and len(parts) > 1:
            candidates.append(self._module_name(parts[1:]))
        candidates.append(self._module_name(parts))
        return list(dict.fromkeys(item for item in candidates if item))
