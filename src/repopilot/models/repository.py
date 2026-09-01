"""Repository scan data contracts."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class RepositorySource(BaseModel):
    """A normalized public GitHub repository source."""

    original_url: str
    normalized_url: str
    owner: str
    name: str
    clone_url: str


class RepositoryFile(BaseModel):
    """Metadata for a safely discovered repository file."""

    relative_path: str
    size_bytes: int = Field(ge=0)
    category: str
    language: str | None = None
    is_text: bool = True
    selection_reason: str | None = None


class ReadFileResult(BaseModel):
    """A bounded text read suitable for a future read_file Tool observation."""

    relative_path: str
    content: str
    size_bytes: int = Field(ge=0)
    bytes_read: int = Field(ge=0)
    truncated: bool = False


class TechnologyEvidence(BaseModel):
    """A deterministic technology detection and its source."""

    name: str
    evidence: str


class EntrypointCandidate(BaseModel):
    """A possible entrypoint found from filenames or configuration."""

    path: str
    reason: str


class RepositoryStats(BaseModel):
    """Resource usage recorded during scanning."""

    total_files: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    text_files: int = Field(ge=0)
    binary_files: int = Field(ge=0)
    skipped_files: int = Field(ge=0)


class RepositorySnapshot(BaseModel):
    """Bounded, serializable facts collected from one repository commit."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: RepositorySource
    commit_sha: str
    root_path: Path
    directory_tree: str
    files: list[RepositoryFile]
    readme_path: str | None = None
    readme_content: str | None = None
    dependency_contents: dict[str, str] = Field(default_factory=dict)
    config_contents: dict[str, str] = Field(default_factory=dict)
    detected_languages: list[TechnologyEvidence] = Field(default_factory=list)
    detected_frameworks: list[TechnologyEvidence] = Field(default_factory=list)
    entrypoint_candidates: list[EntrypointCandidate] = Field(default_factory=list)
    stats: RepositoryStats
    truncation_notes: list[str] = Field(default_factory=list)
