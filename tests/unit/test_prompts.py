from repopilot.llm.prompts import SYSTEM_PROMPT, build_messages
from repopilot.models.analysis import AnalysisRequest


def test_prompt_forbids_invented_entrypoints_and_requests_chinese() -> None:
    assert "may only contain paths explicitly listed" in SYSTEM_PROMPT
    assert "return an empty list" in SYSTEM_PROMPT
    assert "Write explanatory text in Chinese" in SYSTEM_PROMPT


def test_prompt_includes_deterministic_truncation_notes() -> None:
    request = AnalysisRequest(
        repository_name="owner/repo",
        commit_sha="abc",
        context="tree",
        truncated=True,
        truncation_notes=["Context section README was truncated."],
    )

    messages = build_messages(request)

    assert "Context section README was truncated." in messages[1]["content"]
