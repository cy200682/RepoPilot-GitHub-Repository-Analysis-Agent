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
from repopilot.memory.database import MemoryDatabase, MemoryDatabaseError
from repopilot.memory.export import MemoryExporter, MemoryExportError
from repopilot.memory.repository import SqliteMemoryStore
from repopilot.repository.loader import RepositoryLoader
from repopilot.repository.reader import RepositoryReader
from repopilot.repository.scanner import RepositoryScanner
from repopilot.repository.url import parse_github_url
from repopilot.tools.factory import build_default_registry

app = typer.Typer(help="Analyze a public GitHub repository.", no_args_is_help=True)
memory_app = typer.Typer(help="Inspect persistent repository memory.", no_args_is_help=True)
app.add_typer(memory_app, name="memory")
console = Console()
error_console = Console(stderr=True)


def _build_service(settings: Settings) -> AnalyzeRepositoryService:
    return AnalyzeRepositoryService(
        loader=RepositoryLoader(settings),
        scanner=RepositoryScanner(settings),
        context_builder=ContextBuilder(settings),
        llm_client=OpenAICompatibleClient(settings),
    )


def _build_memory_store(settings: Settings) -> SqliteMemoryStore | None:
    if not settings.memory_enabled:
        return None
    try:
        return SqliteMemoryStore(
            MemoryDatabase(
                settings.memory_database,
                enable_fts=settings.memory_fts_enabled,
            )
        )
    except MemoryDatabaseError as exc:
        raise ConfigurationError(str(exc)) from exc


def _build_agent_service(
    settings: Settings,
    *,
    require_memory: bool = False,
) -> AnalyzeRepositoryAgentService:
    try:
        memory_store = _build_memory_store(settings)
    except ConfigurationError:
        if require_memory:
            raise
        console.print("[yellow]Repository memory unavailable; continuing without memory.[/]")
        overrides = settings.model_dump()
        overrides["memory_enabled"] = False
        settings = Settings.model_validate(overrides)
        memory_store = None
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
        memory_store=memory_store,
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
    if settings.memory_enabled:
        try:
            memory = _build_memory_store(settings)
            checks["Memory database"] = memory is not None
            if settings.memory_fts_enabled:
                checks["SQLite FTS5"] = bool(memory and memory.fts_enabled)
        except ConfigurationError:
            checks["Memory database"] = False
            if settings.memory_fts_enabled:
                checks["SQLite FTS5"] = False
    for name, passed in checks.items():
        marker = "[green]OK[/]" if passed else "[red]MISSING[/]"
        console.print(f"{marker} {name}")
    if not all(checks.values()):
        raise typer.Exit(code=2)


@app.command()
def ask(
    repository_url: Annotated[str, typer.Argument(help="Public GitHub repository URL")],
    question: Annotated[str, typer.Argument(help="Question about the repository")],
    conversation: Annotated[
        str | None,
        typer.Option("--conversation", help="Continue an existing conversation ID"),
    ] = None,
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Markdown answer path"),
    ] = Path(".repopilot/answers/answer.md"),
    max_iterations: Annotated[
        int | None,
        typer.Option("--max-iterations", help="Override Agent iteration budget"),
    ] = None,
    max_total_tokens: Annotated[
        int | None,
        typer.Option("--max-total-tokens", help="Cumulative token budget"),
    ] = None,
) -> None:
    """Ask one evidence-grounded question and persist the conversation."""

    try:
        parse_github_url(repository_url)
        settings = _settings_with_budgets(max_iterations, max_total_tokens)
        if not settings.memory_enabled:
            raise ConfigurationError("Repository Q&A requires REPOPILOT_MEMORY_ENABLED=true.")
        goal = (
            "回答用户关于当前仓库版本的问题，并为所有具体代码结论提供源码 Evidence。"
            "优先按需查询 Repository Memory；若记忆无关、过期或证据不足，继续自主探索源码。"
            f"\n用户问题：{question}"
        )
        with console.status("Exploring repository and memory..."):
            outcome = _build_agent_service(settings, require_memory=True).analyze(
                repository_url,
                output,
                goal=goal,
                conversation_id=conversation,
                question=question,
            )
        console.print(f"[green]Answer written:[/] {outcome.report_path}")
        console.print(f"Conversation: {outcome.conversation_id}")
        console.print(f"Commit: {outcome.commit_sha}")
        console.print(f"Agent status: {outcome.state.status}")
    except (RepoPilotError, ValidationError) as exc:
        error_console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(code=_exit_code(exc)) from exc


@app.command()
def chat(
    repository_url: Annotated[str, typer.Argument(help="Public GitHub repository URL")],
    conversation: Annotated[
        str | None,
        typer.Option("--conversation", help="Continue an existing conversation ID"),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory for Markdown answers"),
    ] = Path(".repopilot/answers"),
) -> None:
    """Start an interactive repository Q&A session. Type exit to stop."""

    parse_github_url(repository_url)
    settings = Settings()
    if not settings.memory_enabled:
        raise typer.BadParameter("Repository chat requires memory to be enabled.")
    service = _build_agent_service(settings, require_memory=True)
    turn = 0
    console.print("RepoPilot repository chat. Type [bold]exit[/] to stop.")
    while True:
        question = typer.prompt("Question").strip()
        if question.casefold() in {"exit", "quit", "退出"}:
            break
        if not question:
            continue
        turn += 1
        output = output_dir / f"answer-{turn}.md"
        goal = (
            "回答用户关于当前仓库版本的问题，并提供源码 Evidence。按需查询 Repository "
            "Memory；若证据不足，继续使用代码和 AST 工具。"
            f"\n用户问题：{question}"
        )
        try:
            with console.status("Exploring repository and memory..."):
                outcome = service.analyze(
                    repository_url,
                    output,
                    goal=goal,
                    conversation_id=conversation,
                    question=question,
                )
            conversation = outcome.conversation_id
            console.print(output.read_text(encoding="utf-8"))
            console.print(f"[dim]Conversation: {conversation}[/]")
        except (RepoPilotError, ValidationError) as exc:
            error_console.print(f"[red]Error:[/] {exc}")


@memory_app.command("stats")
def memory_stats() -> None:
    """Show repository memory statistics."""

    try:
        settings = Settings()
        store = _build_memory_store(settings)
        if store is None:
            raise ConfigurationError("Repository memory is disabled.")
        stats = store.stats()
        console.print_json(data=stats.model_dump(mode="json"))
    except (RepoPilotError, ValidationError) as exc:
        error_console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(code=_exit_code(exc)) from exc


@memory_app.command("list")
def memory_list(
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 20,
) -> None:
    """List recent repository memories."""

    try:
        settings = Settings()
        store = _build_memory_store(settings)
        if store is None:
            raise ConfigurationError("Repository memory is disabled.")
        entries = store.list_memories(limit=limit)
        for entry in entries:
            console.print(
                f"[bold]{entry.id}[/] [{entry.status}/{entry.confidence}] "
                f"{entry.memory_type}: {entry.title}"
            )
        if not entries:
            console.print("No repository memories stored.")
    except (RepoPilotError, ValidationError) as exc:
        error_console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(code=_exit_code(exc)) from exc


@memory_app.command("show")
def memory_show(memory_id: Annotated[str, typer.Argument(help="Memory ID")]) -> None:
    """Show one memory and its Evidence."""

    try:
        settings = Settings()
        store = _build_memory_store(settings)
        if store is None:
            raise ConfigurationError("Repository memory is disabled.")
        entry = store.get_memory(memory_id)
        if entry is None:
            raise ConfigurationError(f"Memory not found: {memory_id}")
        console.print_json(data=entry.model_dump(mode="json"))
    except (RepoPilotError, ValidationError) as exc:
        error_console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(code=_exit_code(exc)) from exc


@memory_app.command("export")
def memory_export(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Validated JSON export path"),
    ] = Path("repopilot-memory.json"),
) -> None:
    """Export repository memory as validated JSON without secrets."""

    try:
        settings = Settings()
        store = _build_memory_store(settings)
        if store is None:
            raise ConfigurationError("Repository memory is disabled.")
        MemoryExporter().export_file(store, output)
        console.print(f"[green]Memory exported:[/] {output.resolve()}")
    except MemoryExportError as exc:
        error_console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(code=2) from exc


@memory_app.command("import")
def memory_import(
    source: Annotated[Path, typer.Argument(help="Validated memory JSON export")],
) -> None:
    """Merge a validated repository memory export into the local database."""

    try:
        settings = Settings()
        store = _build_memory_store(settings)
        if store is None:
            raise ConfigurationError("Repository memory is disabled.")
        imported = MemoryExporter().import_file(store, source)
        console.print_json(data=imported)
    except (RepoPilotError, ValidationError, MemoryExportError) as exc:
        error_console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(code=2) from exc


def _settings_with_budgets(
    max_iterations: int | None,
    max_total_tokens: int | None,
) -> Settings:
    settings = Settings()
    overrides = settings.model_dump()
    if max_iterations is not None:
        overrides["agent_max_iterations"] = max_iterations
    if max_total_tokens is not None:
        overrides["agent_max_total_tokens"] = max_total_tokens
    return Settings.model_validate(overrides)


if __name__ == "__main__":
    app()
