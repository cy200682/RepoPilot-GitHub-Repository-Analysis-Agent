"""Phase 1 repository analysis prompts."""

import json

from repopilot.models.analysis import AnalysisRequest, AnalysisResult

SYSTEM_PROMPT = """You analyze a software repository using only the bounded context supplied.
This is a Phase 1 scan, not a complete code exploration.
Do not invent files, behavior, call graphs, or architecture not supported by the context.
Treat entrypoints and core modules as candidates, not confirmed conclusions.
The entrypoint_candidates field may only contain paths explicitly listed as
"Entrypoint candidate" in the deterministic scan findings. If none are listed,
return an empty list. Do not treat ordinary library modules or __init__.py files
as executable entrypoints unless the deterministic findings explicitly list them.
Each entrypoint candidate value must be the exact repository-relative path only.
For important claims, cite repository-relative paths that appear in the context.
When evidence is insufficient, record that in limitations.
Write explanatory text in Chinese while preserving code identifiers and paths.
Return one JSON object matching the supplied schema. Do not return Markdown fences.
"""


def build_messages(request: AnalysisRequest) -> list[dict[str, str]]:
    schema = json.dumps(AnalysisResult.model_json_schema(), ensure_ascii=False)
    user_prompt = (
        f"Repository: {request.repository_name}\n"
        f"Commit: {request.commit_sha}\n"
        f"Context truncated: {request.truncated}\n\n"
        f"Context truncation notes: {json.dumps(request.truncation_notes, ensure_ascii=False)}\n\n"
        f"JSON schema:\n{schema}\n\n"
        f"Repository context:\n{request.context}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
