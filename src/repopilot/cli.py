"""RepoPilot command-line interface."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from repopilot.agent.context import AgentContextBuilder
from repopilot.agent.runtime import AgentRuntime
from repopilot.application.analyze_repository import AnalyzeRepositoryService
from repopilot.application.analyze_repository_agent import (
    DEFAULT_AGENT_GOAL,
    AnalyzeRepositoryAgentService,
)
from repopilot.config import Settings
from repopilot.context.builder import ContextBuilder
from repopilot.exceptions import (
    AgentDecisionError,
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
from repopilot.llm.agent_model import OpenAICompatibleAgentModel
from repopilot.llm.openai_compatible import OpenAICompatibleClient
from repopilot.repository.loader import RepositoryLoader
from repopilot.repository.reader import RepositoryReader
from repopilot.repository.scanner import RepositoryScanner
from repopilot.repository.url import parse_github_url
from repopilot.tools.factory import build_default_registry

app = typer.Typer(help="Analyze a public GitHub repository.", no_args_is_help=True)
console = Console()
error_console = Console(stderr=True)


def _build_service(settings: Settings) -> AnalyzeRepositoryService:
    return AnalyzeRepositoryService(
        loader=RepositoryLoader(settings),
        scanner=RepositoryScanner(settings),
        context_builder=ContextBuilder(settings),
        llm_client=OpenAICompatibleClient(settings),
    )


def _build_agent_service(settings: Settings) -> AnalyzeRepositoryAgentService:
    reader = RepositoryReader(settings)
    registry = build_default_registry(settings)
    runtime = AgentRuntime(
        settings=settings,
        model=OpenAICompatibleAgentModel(settings),
        registry=registry,
        context_builder=AgentContextBuilder(settings),
    )
    return AnalyzeRepositoryAgentService(
        loader=RepositoryLoader(settings),
        scanner=RepositoryScanner(settings, reader),
        reader=reader,
        runtime=runtime,
    )


def _exit_code(exc: Exception) -> int:
    if isinstance(exc, (ConfigurationError, ValidationError)):
        return 2
    if isinstance(exc, InvalidRepositoryUrlError):
        return 3
    if isinstance(exc, (RepositoryNotFoundError, CloneFailedError, CloneTimeoutError)):
        return 4
    if isinstance(exc, (RepositoryTooLargeError, RepositoryScanError, RepositoryReadError)):
        return 5
    if isinstance(exc, (LLMRequestError, LLMResponseError)):
        return 6
    if isinstance(exc, ReportWriteError):
        return 7
    if isinstance(exc, (AgentDecisionError, AgentRunFailedError)):
        return 8
    return 1


@app.command()
def analyze(
    repository_url: Annotated[str, typer.Argument(help="Public GitHub repository URL")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Markdown report path"),
    ] = Path("REPORT.md"),
    keep_repo: Annotated[
        bool,
        typer.Option("--keep-repo", help="Keep the temporary cloned repository"),
    ] = False,
    mode: Annotated[
        str,
        typer.Option("--mode", help="Analysis mode: agent or bootstrap"),
    ] = "agent",
    goal: Annotated[
        str,
        typer.Option("--goal", help="Agent analysis goal"),
    ] = DEFAULT_AGENT_GOAL,
    max_iterations: Annotated[
        int | None,
        typer.Option("--max-iterations", help="Override Agent iteration budget"),
    ] = None,
    max_total_tokens: Annotated[
        int | None,
        typer.Option("--max-total-tokens", help="Stop Agent after this cumulative token budget"),
    ] = None,
    trace_output: Annotated[
        Path | None,
        typer.Option("--trace-output", help="Export Agent trace JSON"),
    ] = None,
) -> None:
    """Analyze one public GitHub repository and write a Markdown report."""

    try:
        parse_github_url(repository_url)
        settings = Settings()
        if mode not in {"agent", "bootstrap"}:
            raise ConfigurationError("--mode must be 'agent' or 'bootstrap'.")
        if max_iterations is not None or max_total_tokens is not None:
            overrides = settings.model_dump()
            if max_iterations is not None:
                overrides["agent_max_iterations"] = max_iterations
            if max_total_tokens is not None:
                overrides["agent_max_total_tokens"] = max_total_tokens
            settings = Settings.model_validate(overrides)
        with console.status("Analyzing repository..."):
            if mode == "agent":
                agent_outcome = _build_agent_service(settings).analyze(
                    repository_url,
                    output,
                    goal=goal,
                    trace_output=trace_output,
                    keep_repository=keep_repo,
                )
                if agent_outcome.state.status == "failed":
                    raise AgentRunFailedError(
                        "Agent run failed; a partial report and requested trace were written."
                    )
            else:
                bootstrap_outcome = _build_service(settings).analyze(
                    repository_url,
                    output,
                    keep_repository=keep_repo,
                )
        if mode == "agent":
            console.print(f"[green]Report written:[/] {agent_outcome.report_path}")
            console.print(f"Commit: {agent_outcome.commit_sha}")
            console.print(f"Agent status: {agent_outcome.state.status}")
            if agent_outcome.trace_path:
                console.print(f"Trace written: {agent_outcome.trace_path}")
            if agent_outcome.snapshot.truncation_notes:
                console.print("[yellow]Some repository content was truncated.[/]")
            if agent_outcome.kept_repository_path:
                console.print(f"Repository kept at: {agent_outcome.kept_repository_path}")
        else:
            console.print(f"[green]Report written:[/] {bootstrap_outcome.report_path}")
            console.print(f"Commit: {bootstrap_outcome.commit_sha}")
            if (
                bootstrap_outcome.snapshot.truncation_notes
                or bootstrap_outcome.request.truncation_notes
            ):
                console.print("[yellow]Some repository content was truncated.[/]")
            if bootstrap_outcome.kept_repository_path:
                console.print(f"Repository kept at: {bootstrap_outcome.kept_repository_path}")
    except (RepoPilotError, ValidationError) as exc:
        error_console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(code=_exit_code(exc)) from exc


@app.command()
def doctor() -> None:
    """Check local Git and required LLM configuration."""

    try:
        settings = Settings()
    except ValidationError as exc:
        console.print(f"[red]Configuration invalid:[/] {exc}")
        raise typer.Exit(code=2) from exc

    checks = {
        "Git executable": shutil.which("git") is not None,
        "LLM API key": bool(settings.llm_api_key),
        "LLM model": bool(settings.llm_model),
        "LLM base URL": bool(settings.llm_base_url),
    }
    for name, passed in checks.items():
        marker = "[green]OK[/]" if passed else "[red]MISSING[/]"
        console.print(f"{marker} {name}")
    if not all(checks.values()):
        raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
