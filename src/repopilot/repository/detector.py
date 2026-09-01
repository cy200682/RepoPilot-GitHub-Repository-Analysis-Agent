"""Deterministic language, framework, and entrypoint detection."""

import tomllib
from collections import Counter
from pathlib import PurePosixPath

from repopilot.models.repository import (
    EntrypointCandidate,
    RepositoryFile,
    TechnologyEvidence,
)
from repopilot.repository.filters import ENTRYPOINT_FILENAMES

FRAMEWORK_DEPENDENCIES = {
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "starlette": "Starlette",
    "typer": "Typer",
    "click": "Click",
    "sqlalchemy": "SQLAlchemy",
    "sqlmodel": "SQLModel",
    "pydantic": "Pydantic",
    "pytest": "pytest",
}


def detect_languages(files: list[RepositoryFile]) -> list[TechnologyEvidence]:
    counts = Counter(file.language for file in files if file.language)
    return [
        TechnologyEvidence(name=name, evidence=f"{count} files detected by extension")
        for name, count in counts.most_common()
    ]


def detect_frameworks(dependency_contents: dict[str, str]) -> list[TechnologyEvidence]:
    results: list[TechnologyEvidence] = []
    for dependency, display_name in FRAMEWORK_DEPENDENCIES.items():
        for path, content in dependency_contents.items():
            if dependency in content.lower():
                results.append(
                    TechnologyEvidence(
                        name=display_name,
                        evidence=f'{path} contains dependency "{dependency}"',
                    )
                )
                break
    return results


def detect_entrypoints(
    files: list[RepositoryFile],
    dependency_contents: dict[str, str] | None = None,
) -> list[EntrypointCandidate]:
    candidates: list[EntrypointCandidate] = []
    for file in files:
        name = PurePosixPath(file.relative_path).name.lower()
        reason = ENTRYPOINT_FILENAMES.get(name)
        if reason:
            candidates.append(EntrypointCandidate(path=file.relative_path, reason=reason))
    candidates.extend(_entrypoints_from_pyproject(files, dependency_contents or {}))
    unique: dict[str, EntrypointCandidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.path, candidate)
    return list(unique.values())


def _entrypoints_from_pyproject(
    files: list[RepositoryFile],
    dependency_contents: dict[str, str],
) -> list[EntrypointCandidate]:
    content = dependency_contents.get("pyproject.toml")
    if not content:
        return []
    try:
        parsed = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return []

    scripts = parsed.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return []

    paths = [file.relative_path for file in files]
    results: list[EntrypointCandidate] = []
    for script_name, target in scripts.items():
        if not isinstance(script_name, str) or not isinstance(target, str):
            continue
        module_name = target.split(":", 1)[0].strip()
        suffix = f"{module_name.replace('.', '/')}.py"
        matches = [path for path in paths if path == suffix or path.endswith(f"/{suffix}")]
        for path in matches:
            results.append(
                EntrypointCandidate(
                    path=path,
                    reason=f'pyproject.toml declares script "{script_name}"',
                )
            )
    return results
