from pathlib import Path

import pytest
from typer.testing import CliRunner

from repopilot import cli
from repopilot.cli import _exit_code, app
from repopilot.exceptions import (
    AgentRunFailedError,
    CloneFailedError,
    CloneTimeoutError,
    ConfigurationError,
    InvalidRepositoryUrlError,
    LLMRequestError,
    LLMResponseError,
    RepoPilotError,
    ReportWriteError,
    RepositoryNotFoundError,
    RepositoryReadError,
    RepositoryScanError,
    RepositoryTooLargeError,
)

runner = CliRunner()


def test_doctor_reports_missing_llm_configuration() -> None:
    result = runner.invoke(
        app,
        ["doctor"],
        env={
            "REPOPILOT_LLM_API_KEY": "",
            "REPOPILOT_LLM_MODEL": "",
        },
    )

    assert result.exit_code == 2
    assert "MISSING LLM API key" in result.stdout
    assert "MISSING LLM model" in result.stdout


def test_analyze_validates_url_before_llm_configuration() -> None:
    result = runner.invoke(app, ["analyze", "file:///tmp/repo"])

    assert result.exit_code == 3
    assert "Only public HTTPS GitHub" in result.output


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ConfigurationError("bad config"), 2),
        (InvalidRepositoryUrlError("bad url"), 3),
        (RepositoryNotFoundError("missing"), 4),
        (CloneFailedError("failed"), 4),
        (CloneTimeoutError("timeout"), 4),
        (RepositoryTooLargeError("large"), 5),
        (RepositoryScanError("scan"), 5),
        (RepositoryReadError("read"), 5),
        (LLMRequestError("request"), 6),
        (LLMResponseError("response"), 6),
        (ReportWriteError("write"), 7),
        (AgentRunFailedError("agent failed"), 8),
        (RepoPilotError("unknown"), 1),
    ],
)
def test_exit_code_mapping(error: Exception, expected: int) -> None:
    assert _exit_code(error) == expected


def test_agent_failed_status_returns_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailedAgentService:
        def analyze(self, *args: object, **kwargs: object) -> object:
            del args, kwargs

            class Outcome:
                class State:
                    status = "failed"

                state = State()

            return Outcome()

    monkeypatch.setattr(cli, "_build_agent_service", lambda settings: FailedAgentService())

    result = runner.invoke(app, ["analyze", "https://github.com/example/project"])

    assert result.exit_code == 8
    assert "partial report" in result.output


def test_cli_applies_iteration_and_token_budget_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, int] = {}

    class CompletedAgentService:
        def analyze(self, *args: object, **kwargs: object) -> object:
            del args, kwargs

            class Outcome:
                class State:
                    status = "completed"

                class Snapshot:
                    truncation_notes: list[str] = []

                state = State()
                snapshot = Snapshot()
                report_path = Path("REPORT.md")
                commit_sha = "fixture-sha"
                trace_path = None
                kept_repository_path = None

            return Outcome()

    def build(settings: object) -> CompletedAgentService:
        captured["iterations"] = settings.agent_max_iterations  # type: ignore[attr-defined]
        captured["tokens"] = settings.agent_max_total_tokens  # type: ignore[attr-defined]
        return CompletedAgentService()

    monkeypatch.setattr(cli, "_build_agent_service", build)

    result = runner.invoke(
        app,
        [
            "analyze",
            "https://github.com/example/project",
            "--max-iterations",
            "6",
            "--max-total-tokens",
            "30000",
        ],
    )

    assert result.exit_code == 0
    assert captured == {"iterations": 6, "tokens": 30_000}
