"""Bounded and deterministic repository scanning."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from repopilot.config import Settings
from repopilot.exceptions import RepositoryReadError, RepositoryScanError, RepositoryTooLargeError
from repopilot.models.repository import (
    RepositoryFile,
    RepositorySnapshot,
    RepositorySource,
    RepositoryStats,
)
from repopilot.repository.detector import (
    detect_entrypoints,
    detect_frameworks,
    detect_languages,
)
from repopilot.repository.filters import classify_file, detect_language, is_excluded_directory
from repopilot.repository.reader import RepositoryReader, RepositoryReaderProtocol


class RepositoryScanner:
    """Collect bounded repository facts without executing target code."""

    def __init__(
        self,
        settings: Settings,
        reader: RepositoryReaderProtocol | None = None,
    ) -> None:
        self.settings = settings
        self.reader = reader or RepositoryReader(settings)

    def scan(
        self,
        root_path: Path,
        source: RepositorySource,
        commit_sha: str,
    ) -> RepositorySnapshot:
        root = root_path.resolve()
        if not root.is_dir():
            raise RepositoryScanError(f"Repository root does not exist: {root}")

        files: list[RepositoryFile] = []
        dependency_contents: dict[str, str] = {}
        config_contents: dict[str, str] = {}
        readme_path: str | None = None
        readme_content: str | None = None
        truncation_notes: list[str] = []
        total_bytes = 0
        text_files = 0
        binary_files = 0
        skipped_files = 0

        try:
            for path in self._iter_files(root, truncation_notes):
                try:
                    path.resolve().relative_to(root)
                except (OSError, ValueError):
                    skipped_files += 1
                    continue
                relative = path.relative_to(root).as_posix()
                try:
                    size = path.stat().st_size
                except OSError:
                    skipped_files += 1
                    continue

                total_bytes += size
                if total_bytes > self.settings.max_repo_mb * 1024 * 1024:
                    raise RepositoryTooLargeError(
                        f"Repository exceeds the {self.settings.max_repo_mb} MB scan limit."
                    )

                is_text = self.reader.is_text_file(root, relative)
                category = classify_file(relative)
                repository_file = RepositoryFile(
                    relative_path=relative,
                    size_bytes=size,
                    category=category,
                    language=detect_language(relative),
                    is_text=is_text,
                )
                files.append(repository_file)

                if not is_text:
                    binary_files += 1
                    continue
                text_files += 1

                if size > self.settings.max_file_bytes and category in {
                    "readme",
                    "dependency",
                    "config",
                }:
                    truncation_notes.append(
                        f"{relative} exceeded the per-file limit and was truncated."
                    )

                if category in {"readme", "dependency", "config"}:
                    try:
                        read_result = self.reader.read_file(root, relative)
                    except RepositoryReadError as exc:
                        skipped_files += 1
                        truncation_notes.append(str(exc))
                        continue
                    content = read_result.content
                    truncated = read_result.truncated
                    already_noted = any(note.startswith(relative) for note in truncation_notes)
                    if truncated and not already_noted:
                        truncation_notes.append(f"{relative} was truncated while reading.")
                    if category == "readme" and readme_content is None:
                        readme_path = relative
                        readme_content = content
                    elif category == "dependency":
                        dependency_contents[relative] = content
                    elif category == "config":
                        config_contents[relative] = content

        except RepositoryTooLargeError:
            raise
        except OSError as exc:
            raise RepositoryScanError(f"Could not scan repository: {exc}") from exc

        files.sort(key=lambda item: item.relative_path.lower())
        tree = self._build_tree(files, truncation_notes)
        return RepositorySnapshot(
            source=source,
            commit_sha=commit_sha,
            root_path=root,
            directory_tree=tree,
            files=files,
            readme_path=readme_path,
            readme_content=readme_content,
            dependency_contents=dependency_contents,
            config_contents=config_contents,
            detected_languages=detect_languages(files),
            detected_frameworks=detect_frameworks(dependency_contents),
            entrypoint_candidates=detect_entrypoints(files, dependency_contents),
            stats=RepositoryStats(
                total_files=len(files),
                total_bytes=total_bytes,
                text_files=text_files,
                binary_files=binary_files,
                skipped_files=skipped_files,
            ),
            truncation_notes=truncation_notes,
        )

    def _iter_files(self, root: Path, notes: list[str]) -> Iterator[Path]:
        yielded = 0
        for current, directory_names, file_names in os.walk(root, followlinks=False):
            current_path = Path(current)
            depth = len(current_path.relative_to(root).parts)
            directory_names[:] = sorted(
                name
                for name in directory_names
                if not is_excluded_directory(name)
                and not self.reader.is_link_or_junction(current_path / name)
            )
            if depth >= self.settings.max_depth:
                if directory_names:
                    relative_current = current_path.relative_to(root)
                    notes.append(f"Directories below {relative_current} were skipped.")
                directory_names[:] = []

            for name in sorted(file_names):
                path = current_path / name
                if self.reader.is_link_or_junction(path):
                    continue
                yielded += 1
                if yielded > self.settings.max_files:
                    notes.append(f"File list was limited to {self.settings.max_files} entries.")
                    return
                yield path

    def _build_tree(self, files: list[RepositoryFile], notes: list[str]) -> str:
        lines = [file.relative_path for file in files]
        tree = "\n".join(lines)
        if len(tree) > self.settings.max_tree_chars:
            tree = tree[: self.settings.max_tree_chars].rsplit("\n", 1)[0]
            notes.append(
                f"Directory tree was truncated to {self.settings.max_tree_chars} characters."
            )
        return tree
