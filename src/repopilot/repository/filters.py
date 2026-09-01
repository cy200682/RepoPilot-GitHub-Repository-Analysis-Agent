"""Centralized repository traversal and file classification rules."""

from pathlib import PurePosixPath

EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        "node_modules",
        "venv",
        ".venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tmp",
        ".repopilot",
        "build",
        "dist",
        "coverage",
        "htmlcov",
        "target",
        "vendor",
    }
)

DEPENDENCY_FILENAMES = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "pipfile",
        "poetry.lock",
        "uv.lock",
    }
)

CONFIG_FILENAMES = frozenset(
    {
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "tox.ini",
        "mypy.ini",
        "pytest.ini",
        ".pre-commit-config.yaml",
    }
)

ENTRYPOINT_FILENAMES = {
    "main.py": "conventional Python application entrypoint",
    "app.py": "conventional Python application entrypoint",
    "cli.py": "conventional command-line entrypoint",
    "manage.py": "conventional framework management entrypoint",
    "__main__.py": "Python module execution entrypoint",
    "wsgi.py": "WSGI application entrypoint",
    "asgi.py": "ASGI application entrypoint",
}

LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".cc": "C++",
    ".c": "C",
    ".h": "C/C++ Header",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sh": "Shell",
    ".ps1": "PowerShell",
}


def is_excluded_directory(name: str) -> bool:
    return name.lower() in EXCLUDED_DIRECTORIES


def classify_file(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    name = path.name.lower()
    if name.startswith("readme"):
        return "readme"
    if name in DEPENDENCY_FILENAMES or name.startswith("requirements") and name.endswith(".txt"):
        return "dependency"
    if (
        name in CONFIG_FILENAMES
        or relative_path.startswith(".github/workflows/")
        and path.suffix.lower() in {".yml", ".yaml"}
    ):
        return "config"
    if name in ENTRYPOINT_FILENAMES:
        return "entrypoint"
    if path.suffix.lower() in LANGUAGE_BY_SUFFIX:
        return "source"
    if path.suffix.lower() in {".md", ".rst", ".txt"}:
        return "documentation"
    return "other"


def detect_language(relative_path: str) -> str | None:
    return LANGUAGE_BY_SUFFIX.get(PurePosixPath(relative_path).suffix.lower())
