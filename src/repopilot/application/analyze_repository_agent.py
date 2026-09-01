"""Application service for Phase 2 Agent exploration."""

import json
from dataclasses import dataclass
from pathlib import Path

from repopilot.agent.context import build_bootstrap_summary
from repopilot.agent.runtime import AgentRuntime
from repopilot.agent.state import AgentState
from repopilot.application.protocols import RepositoryLoaderProtocol, RepositoryScannerProtocol
from repopilot.exceptions import AgentRunFailedError, ReportWriteError
from repopilot.models.repository import RepositorySnapshot
from repopilot.report.agent_renderer import AgentMarkdownReportRenderer
from repopilot.repository.reader import RepositoryReaderProtocol
from repopilot.repository.url import parse_github_url
from repopilot.tools.factory import build_tool_context

DEFAULT_AGENT_GOAL = (
    "分析该仓库的项目定位、程序入口、核心模块、主要执行流程、重要设计、"
    "潜在问题和推荐阅读顺序，并为关键结论提供源码证据。"
)


@dataclass(slots=True)
class AgentAnalysisOutcome:
    report_path: Path
    trace_path: Path | None
    commit_sha: str
    snapshot: RepositorySnapshot
    state: AgentState
    kept_repository_path: Path | None = None


class AnalyzeRepositoryAgentService:
    def __init__(
        self,
        loader: RepositoryLoaderProtocol,
        scanner: RepositoryScannerProtocol,
        reader: RepositoryReaderProtocol,
        runtime: AgentRuntime,
        renderer: AgentMarkdownReportRenderer | None = None,
    ) -> None:
        self.loader = loader
        self.scanner = scanner
        self.reader = reader
        self.runtime = runtime
        self.renderer = renderer or AgentMarkdownReportRenderer()

    def analyze(
        self,
        repository_url: str,
        output_path: Path,
        *,
        goal: str = DEFAULT_AGENT_GOAL,
        trace_output: Path | None = None,
        keep_repository: bool = False,
    ) -> AgentAnalysisOutcome:
        source = parse_github_url(repository_url)
        loaded = self.loader.clone(source)
        try:
            snapshot = self.scanner.scan(loaded.root_path, source, loaded.commit_sha)
            state = AgentState(
                goal=goal,
                repository_url=source.normalized_url,
                commit_sha=loaded.commit_sha,
                bootstrap_summary=build_bootstrap_summary(snapshot),
            )
            run = self.runtime.run(
                state,
                build_tool_context(
                    self.runtime.settings,
                    loaded.root_path,
                    snapshot,
                    self.reader,
                ),
            )
            analysis = run.state.final_analysis
            if analysis is None:
                raise AgentRunFailedError("Agent Runtime ended without an analysis result.")
            trace_path = trace_output.resolve() if trace_output else None
            report = self.renderer.render(
                analysis,
                snapshot,
                run.state,
                str(trace_path) if trace_path else None,
            )
            self._write_text(output_path, report)
            if trace_output:
                self._write_text(
                    trace_output,
                    json.dumps(run.trace.model_dump(mode="json"), ensure_ascii=False, indent=2),
                )
            return AgentAnalysisOutcome(
                report_path=output_path.resolve(),
                trace_path=trace_path,
                commit_sha=loaded.commit_sha,
                snapshot=snapshot,
                state=run.state,
                kept_repository_path=loaded.root_path if keep_repository else None,
            )
        finally:
            if not keep_repository:
                self.loader.cleanup(loaded)

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise ReportWriteError(f"Could not write {path}: {exc}") from exc
