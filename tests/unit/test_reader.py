from pathlib import Path

import pytest

from repopilot.config import Settings
from repopilot.exceptions import RepositoryReadError
from repopilot.repository.reader import RepositoryReader


def test_reader_returns_bounded_text(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    path.write_text("0123456789", encoding="utf-8")
    reader = RepositoryReader(Settings(max_file_bytes=100))

    result = reader.read_file(tmp_path, "module.py", max_bytes=5)

    assert result.content == "01234"
    assert result.bytes_read == 5
    assert result.size_bytes == 10
    assert result.truncated is True


@pytest.mark.parametrize("path", ["../secret.txt", "/absolute.txt", "..\\secret.txt"])
def test_reader_rejects_paths_outside_repository(tmp_path: Path, path: str) -> None:
    reader = RepositoryReader(Settings())

    with pytest.raises(RepositoryReadError):
        reader.read_file(tmp_path, path)


def test_reader_rejects_binary_file(tmp_path: Path) -> None:
    (tmp_path / "binary.bin").write_bytes(b"hello\x00world")
    reader = RepositoryReader(Settings())

    with pytest.raises(RepositoryReadError, match="Binary"):
        reader.read_file(tmp_path, "binary.bin")


def test_reader_rejects_missing_file(tmp_path: Path) -> None:
    reader = RepositoryReader(Settings())

    with pytest.raises(RepositoryReadError, match="does not exist"):
        reader.read_file(tmp_path, "missing.py")
