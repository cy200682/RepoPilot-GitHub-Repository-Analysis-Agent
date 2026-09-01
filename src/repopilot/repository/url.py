"""Strict normalization for supported public GitHub repository URLs."""

import re
from urllib.parse import unquote, urlsplit, urlunsplit

from repopilot.exceptions import InvalidRepositoryUrlError
from repopilot.models.repository import RepositorySource


def parse_github_url(url: str) -> RepositorySource:
    """Validate and normalize a public GitHub HTTPS repository URL."""

    raw = url.strip()
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise InvalidRepositoryUrlError("The repository URL is malformed.") from exc

    if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() != "github.com":
        raise InvalidRepositoryUrlError("Only public HTTPS GitHub repository URLs are supported.")
    if parsed.username or parsed.password or parsed.port:
        raise InvalidRepositoryUrlError("Credentials and custom ports are not allowed in the URL.")
    if parsed.query or parsed.fragment:
        raise InvalidRepositoryUrlError("Query strings and fragments are not supported.")

    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise InvalidRepositoryUrlError(
            "Expected a URL in the form https://github.com/owner/repository."
        )

    owner, name = parts
    if name.lower().endswith(".git"):
        name = name[:-4]
    if not owner or not name or owner in {".", ".."} or name in {".", ".."}:
        raise InvalidRepositoryUrlError("The repository owner and name must be non-empty.")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", owner):
        raise InvalidRepositoryUrlError("The GitHub repository owner is invalid.")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise InvalidRepositoryUrlError("The repository owner or name contains invalid characters.")

    path = f"/{owner}/{name}"
    normalized = urlunsplit(("https", "github.com", path, "", ""))
    return RepositorySource(
        original_url=raw,
        normalized_url=normalized,
        owner=owner,
        name=name,
        clone_url=f"{normalized}.git",
    )
