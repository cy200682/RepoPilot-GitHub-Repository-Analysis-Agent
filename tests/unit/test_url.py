import pytest

from repopilot.exceptions import InvalidRepositoryUrlError
from repopilot.repository.url import parse_github_url


@pytest.mark.parametrize(
    ("url", "normalized"),
    [
        (
            "https://github.com/openai/openai-python",
            "https://github.com/openai/openai-python",
        ),
        (
            "https://github.com/openai/openai-python.git",
            "https://github.com/openai/openai-python",
        ),
        (
            "  https://GITHUB.com/owner/repo  ",
            "https://github.com/owner/repo",
        ),
    ],
)
def test_parse_github_url(url: str, normalized: str) -> None:
    assert parse_github_url(url).normalized_url == normalized


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:owner/repo.git",
        "http://github.com/owner/repo",
        "https://gitlab.com/owner/repo",
        "https://token@github.com/owner/repo",
        "https://github.com/owner/repo/tree/main",
        "https://github.com/owner%2Frepo/name",
        "file:///tmp/repo",
        "https://github.com/owner",
    ],
)
def test_parse_github_url_rejects_unsupported_sources(url: str) -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        parse_github_url(url)
