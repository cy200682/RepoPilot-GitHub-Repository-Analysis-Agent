"""Clone lifecycle for public repositories."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from git import Repo

from repopilot.config import Settings
from repopilot.exceptions import (
    CloneFailedError,
    CloneTimeoutError,
    RepositoryNotFoundError,
)
from repopilot.models.repository import RepositorySource


@dataclass(slots=True)
class LoadedRepository:
    """A checked-out repository and its lifecycle metadata."""

    source: RepositorySource
    root_path: Path
    commit_sha: str
    task_path: Path


class RepositoryLoader:
    """Create and clean bounded shallow repository checkouts."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def clone(self, source: RepositorySource) -> LoadedRepository:
        base_dir = self.settings.workspace_dir
        if base_dir is not None:
            base_dir.mkdir(parents=True, exist_ok=True)
        task_path = Path(tempfile.mkdtemp(prefix="repopilot-", dir=base_dir))
        repository_path = task_path / "repository"

        try:
            git_executable = shutil.which("git")
            if git_executable is None:
                raise CloneFailedError("Git is not installed or is not available on PATH.")
            subprocess.run(
                [
                    git_executable,
                    "clone",
                    "--depth=1",
                    "--single-branch",
                    "--no-tags",
                    "--no-recurse-submodules",
                    "--",
                    source.clone_url,
                    str(repository_path),
                ],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.settings.clone_timeout_seconds,
                check=True,
            )
            repo = Repo(repository_path)
            commit_sha = repo.head.commit.hexsha
            repo.close()
            return LoadedRepository(
                source=source,
                root_path=repository_path.resolve(),
                commit_sha=commit_sha,
                task_path=task_path.resolve(),
            )
        except subprocess.TimeoutExpired as exc:
            self.cleanup_path(task_path)
            raise CloneTimeoutError(
                f"Cloning {source.normalized_url} exceeded the configured timeout."
            ) from exc
        except subprocess.CalledProcessError as exc:
            self.cleanup_path(task_path)
            message = self._safe_process_error(exc)
            lowered = message.lower()
            if any(marker in lowered for marker in ("not found", "repository not found", "403")):
                raise RepositoryNotFoundError(
                    "The public repository was not found or is not accessible."
                ) from exc
            raise CloneFailedError(f"Git clone failed: {message}") from exc
        except Exception as exc:
            self.cleanup_path(task_path)
            raise CloneFailedError(f"Could not clone the repository: {exc}") from exc

    @staticmethod
    def cleanup(loaded: LoadedRepository) -> None:
        RepositoryLoader.cleanup_path(loaded.task_path)

    @staticmethod
    def cleanup_path(path: Path) -> None:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _safe_process_error(exc: subprocess.CalledProcessError) -> str:
        stderr = str(exc.stderr or "").strip()
        return stderr[-500:] if stderr else "Git returned a non-zero exit status."
