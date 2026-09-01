"""Validate model-provided evidence against a repository snapshot."""

from pathlib import PurePosixPath

from repopilot.models.analysis import AnalysisResult
from repopilot.models.repository import RepositorySnapshot


def validate_evidence(
    result: AnalysisResult,
    snapshot: RepositorySnapshot,
) -> AnalysisResult:
    """Mark only safe, existing repository-relative paths as verified."""

    known_paths = {file.relative_path for file in snapshot.files}
    validated = result.model_copy(deep=True)
    allowed_entrypoints = {candidate.path for candidate in snapshot.entrypoint_candidates}
    original_entrypoint_count = len(validated.entrypoint_candidates)
    validated.entrypoint_candidates = list(
        dict.fromkeys(
            candidate
            for candidate in validated.entrypoint_candidates
            if candidate in allowed_entrypoints
        )
    )
    removed_entrypoints = original_entrypoint_count - len(validated.entrypoint_candidates)
    if removed_entrypoints:
        validated.limitations.append(
            f"已移除 {removed_entrypoints} 个不在 Scanner 候选集合中的入口推断。"
        )
    for evidence in validated.evidence:
        normalized = PurePosixPath(evidence.path.replace("\\", "/"))
        safe = (
            not normalized.is_absolute()
            and ".." not in normalized.parts
            and normalized.as_posix() in known_paths
        )
        evidence.path = normalized.as_posix()
        evidence.verified = safe
    return validated
