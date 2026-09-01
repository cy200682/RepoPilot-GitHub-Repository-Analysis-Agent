from types import SimpleNamespace

import pytest

from repopilot.config import Settings
from repopilot.exceptions import LLMRequestError, LLMResponseError
from repopilot.llm.openai_compatible import OpenAICompatibleClient
from repopilot.models.analysis import AnalysisRequest


class FakeCompletions:
    def __init__(self, content: str) -> None:
        self.content = content

    def create(self, **_: object) -> object:
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FailingCompletions:
    def create(self, **_: object) -> object:
        raise RuntimeError("request failed with secret-key")


def fake_sdk(content: str) -> object:
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(content)))


def test_openai_compatible_client_validates_json() -> None:
    settings = Settings(llm_api_key="test", llm_model="test-model")
    client = OpenAICompatibleClient(settings, client=fake_sdk('{"project_summary":"ok"}'))  # type: ignore[arg-type]

    result = client.analyze_repository(
        AnalysisRequest(repository_name="o/r", commit_sha="abc", context="files")
    )

    assert result.project_summary == "ok"


def test_openai_compatible_client_rejects_invalid_json() -> None:
    settings = Settings(llm_api_key="test", llm_model="test-model")
    client = OpenAICompatibleClient(settings, client=fake_sdk("not-json"))  # type: ignore[arg-type]

    with pytest.raises(LLMResponseError):
        client.analyze_repository(
            AnalysisRequest(repository_name="o/r", commit_sha="abc", context="files")
        )


def test_openai_compatible_client_redacts_api_key_from_errors() -> None:
    settings = Settings(llm_api_key="secret-key", llm_model="test-model")
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions()))
    client = OpenAICompatibleClient(settings, client=sdk)  # type: ignore[arg-type]

    with pytest.raises(LLMRequestError) as captured:
        client.analyze_repository(
            AnalysisRequest(repository_name="o/r", commit_sha="abc", context="files")
        )

    assert "secret-key" not in str(captured.value)
    assert "[REDACTED]" in str(captured.value)
