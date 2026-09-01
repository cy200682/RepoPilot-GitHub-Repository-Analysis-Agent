import subprocess
from pathlib import Path

import pytest

from repopilot.config import Settings
from repopilot.exceptions import CloneTimeoutError
from repopilot.models.repository import RepositorySource
from repopilot.repository.loader import RepositoryLoader


def test_loader_maps_subprocess_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    repository_source: RepositorySource,
) -> None:
    settings = Settings(workspace_dir=tmp_path, clone_timeout_seconds=1)
    loader = RepositoryLoader(settings)

    monkeypatch.setattr("repopilot.repository.loader.shutil.which", lambda _: "git")

    def timeout(*_: object, **__: object) -> None:
        raise subprocess.TimeoutExpired(cmd="git clone", timeout=1)

    monkeypatch.setattr("repopilot.repository.loader.subprocess.run", timeout)

    with pytest.raises(CloneTimeoutError):
        loader.clone(repository_source)

    assert list(tmp_path.iterdir()) == []
