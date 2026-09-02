"""Application service for Phase 2 Agent exploration."""

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from repopilot.agent.context import build_bootstrap_summary
from repopilot.agent.runtime import AgentRuntime
from repopilot.agent.state import AgentState
from repopilot.application.protocols import RepositoryLoaderProtocol, RepositoryScannerProtocol
from repopilot.exceptions import AgentRunFailedError, ReportWriteError, RepositoryReadError
from repopilot.memory.models import ExplorationEpisode, MemoryCandidate, MemoryEvidence
from repopilot.memory.repository import SqliteMemoryStore
from repopilot.memory.safety import redact_memory_text
from repopilot.memory.summarizer import ConversationSummarizer
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
    conversation_id: str | None = None


class AnalyzeRepositoryAgentService:
    def __init__(
        self,
        loader: RepositoryLoaderProtocol,
        scanner: RepositoryScannerProtocol,
        reader: RepositoryReaderProtocol,
        runtime: AgentRuntime,
        renderer: AgentMarkdownReportRenderer | None = None,
        memory_store: SqliteMemoryStore | None = None,
    ) -> None:
        self.loader = loader
        self.scanner = scanner
        self.reader = reader
        self.runtime = runtime
        self.renderer = renderer or AgentMarkdownReportRenderer()
        self.memory_store = memory_store

    def analyze(
        self,
        repository_url: str,
        output_path: Path,
        *,
        goal: str = DEFAULT_AGENT_GOAL,
        trace_output: Path | None = None,
        keep_repository: bool = False,
        conversation_id: str | None = None,
        question: str | None = None,
    ) -> AgentAnalysisOutcome:
        source = parse_github_url(repository_url)
        loaded = self.loader.clone(source)
        try:
            snapshot = self.scanner.scan(loaded.root_path, source, loaded.commit_sha)
            repository_id: str | None = None
            revision_id: str | None = None
            conversation_summary = ""
            recent_messages: list[str] = []
            if self.memory_store is not None:
                repository = self.memory_store.get_or_create_repository(source)
                revision = self.memory_store.get_or_create_revision(
                    repository.id,
                    loaded.commit_sha,
                    detected_stack=[item.name for item in snapshot.detected_languages]
                    + [item.name for item in snapshot.detected_frameworks],
                )
                repository_id = repository.id
                revision_id = revision.id
                if question is not None:
                    conversation_id, conversation_summary, recent_messages = (
                        self._prepare_conversation(
                            repository_id,
                            revision_id,
                            question,
                            conversation_id,
                        )
                    )
            state = AgentState(
                goal=goal,
                repository_url=source.normalized_url,
                commit_sha=loaded.commit_sha,
                bootstrap_summary=build_bootstrap_summary(snapshot),
                memory_catalog=(
                    self.memory_store.memory_catalog(repository_id, revision_id)
                    if self.memory_store is not None and repository_id and revision_id
                    else {}
                ),
                conversation_id=conversation_id,
                conversation_summary=conversation_summary,
                recent_messages=recent_messages,
            )
            run = self.runtime.run(
                state,
                build_tool_context(
                    self.runtime.settings,
                    loaded.root_path,
                    snapshot,
                    self.reader,
                    memory_store=self.memory_store,
                    memory_repository_id=repository_id,
                    memory_revision_id=revision_id,
                    memory_run_id=state.run_id,
                    memory_catalog=state.memory_catalog,
                ),
            )
            analysis = run.state.final_analysis
            if analysis is None:
                raise AgentRunFailedError("Agent Runtime ended without an analysis result.")
            trace_path = trace_output.resolve() if trace_output else None
            if self.memory_store is not None and repository_id and revision_id:
                self._persist_run_memory(
                    repository_id,
                    revision_id,
                    run,
                    output_path,
                    trace_path,
                    snapshot,
                )
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
            if (
                self.memory_store is not None
                and repository_id
                and revision_id
                and conversation_id
                and question is not None
            ):
                self.memory_store.append_message(
                    conversation_id,
                    "assistant",
                    self._safe_memory_text(report),
                    answer_status=run.state.status,
                    source_run_id=run.state.run_id,
                    evidence_ids=[item.evidence_id for item in analysis.evidence if item.verified],
                    token_usage={
                        "prompt_tokens": run.state.prompt_tokens,
                        "completion_tokens": run.state.completion_tokens,
                        "total_tokens": run.state.total_tokens,
                        "estimated": run.state.token_usage_estimated,
                    },
                )
            return AgentAnalysisOutcome(
                report_path=output_path.resolve(),
                trace_path=trace_path,
                commit_sha=loaded.commit_sha,
                snapshot=snapshot,
                state=run.state,
                kept_repository_path=loaded.root_path if keep_repository else None,
                conversation_id=conversation_id,
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

    def _prepare_conversation(
        self,
        repository_id: str,
        revision_id: str,
        question: str,
        conversation_id: str | None,
    ) -> tuple[str, str, list[str]]:
        assert self.memory_store is not None
        if conversation_id:
            conversation = self.memory_store.get_conversation(conversation_id)
            if conversation is None:
                raise AgentRunFailedError(f"Conversation not found: {conversation_id}")
            if conversation.repository_id != repository_id:
                raise AgentRunFailedError("Conversation belongs to a different repository.")
            if conversation.revision_id != revision_id:
                raise AgentRunFailedError(
                    "Repository commit changed; start a new conversation for the new revision."
                )
        else:
            conversation = self.memory_store.create_conversation(
                repository_id,
                revision_id,
                self._safe_memory_text(question[:120]),
            )
            conversation_id = conversation.id
        self.memory_store.append_message(
            conversation_id,
            "user",
            self._safe_memory_text(question),
        )
        messages = self.memory_store.list_messages(conversation_id, limit=100)
        recent_count = self.runtime.settings.conversation_recent_messages
        older = messages[:-recent_count]
        unsummarized = [
            item for item in older if item.sequence > conversation.summarized_through_sequence
        ]
        if unsummarized and sum(len(item.content) for item in messages) >= (
            self.runtime.settings.conversation_summary_trigger_chars
        ):
            summarizer = ConversationSummarizer(
                self.runtime.settings.conversation_summary_max_chars
            )
            summary = summarizer.summarize(conversation.summary, unsummarized)
            self.memory_store.update_conversation_summary(
                conversation_id,
                summary,
                unsummarized[-1].sequence,
            )
            conversation_summary = summary
        else:
            conversation_summary = conversation.summary
        recent = [f"{item.role}: {item.content[:2000]}" for item in messages[-recent_count:]]
        return conversation_id, conversation_summary, recent

    def _persist_run_memory(
        self,
        repository_id: str,
        revision_id: str,
        run: object,
        output_path: Path,
        trace_path: Path | None,
        snapshot: RepositorySnapshot,
    ) -> None:
        from repopilot.agent.runtime import AgentRunResult

        assert self.memory_store is not None
        if not isinstance(run, AgentRunResult):
            return
        self.memory_store.save_analysis_run(
            revision_id,
            run.state,
            model_name=self.runtime.settings.llm_model,
            report_path=str(output_path.resolve()),
            trace_path=str(trace_path) if trace_path else None,
            started_at=run.trace.started_at,
            ended_at=run.trace.ended_at,
        )
        analysis = run.state.final_analysis
        saved = 0
        if analysis is not None:
            evidence = {item.evidence_id: item for item in analysis.evidence if item.verified}
            sections = {
                "entry_point": analysis.entrypoints,
                "core_module": analysis.core_modules,
                "execution_flow": analysis.execution_flows,
                "module_relationship": analysis.module_relationships,
            }
            for memory_type, findings in sections.items():
                for finding in findings:
                    if saved >= self.runtime.settings.memory_max_saves_per_run:
                        break
                    selected = [evidence[item] for item in finding.evidence_ids if item in evidence]
                    if not selected:
                        continue
                    candidate = MemoryCandidate.model_validate(
                        {
                            "memory_type": memory_type,
                            "title": self._safe_memory_text(finding.claim[:300]),
                            "content": self._safe_memory_text(finding.claim),
                            "tags": self._memory_tags(self._safe_memory_text(finding.claim)),
                            "symbol_names": [
                                symbol for symbol in analysis.key_symbols if symbol in finding.claim
                            ][:10],
                            "paths": sorted({item.path for item in selected}),
                            "confidence": finding.confidence,
                            "evidence": [
                                MemoryEvidence(
                                    evidence_id=item.evidence_id,
                                    observation_id=item.observation_id,
                                    source_kind=item.source_kind,
                                    resolution=item.resolution,
                                    path=item.path,
                                    start_line=item.start_line,
                                    end_line=item.end_line,
                                    content_hash=self._source_hash(snapshot, item.path),
                                    verified=item.verified,
                                )
                                for item in selected
                            ],
                            "coverage_notes": analysis.limitations[:10],
                        }
                    )
                    stored = self.memory_store.save_memory(
                        repository_id,
                        revision_id,
                        snapshot.commit_sha,
                        run.state.run_id,
                        candidate,
                    )
                    if stored.match_kind != "deduplicated":
                        saved += 1
                        self.memory_store.record_memory_usage(
                            run.state.run_id,
                            stored.id,
                            selected[0].observation_id,
                            "saved",
                        )
                if saved >= self.runtime.settings.memory_max_saves_per_run:
                    break
        run.state.memory_entries_saved += saved
        run.trace.memory_entries_saved = run.state.memory_entries_saved
        tools_used = [
            step.decision.action.tool_name
            for step in run.trace.steps
            if step.decision is not None and hasattr(step.decision.action, "tool_name")
        ]
        self.memory_store.save_exploration_episode(
            ExplorationEpisode(
                run_id=run.state.run_id,
                revision_id=revision_id,
                goal=run.state.goal,
                explored_paths=sorted(run.state.visited_files | run.state.ast_parsed_files),
                tools_used=tools_used,
                confirmed_summary=(analysis.project_summary if analysis else ""),
                unresolved_questions=(analysis.limitations if analysis else []),
                coverage_notes=snapshot.truncation_notes,
                stop_reason=run.state.status,
            )
        )

    @staticmethod
    def _memory_tags(text: str) -> list[str]:
        words = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*|[\u4e00-\u9fff]{2,8}", text)
        result: list[str] = []
        for word in words:
            if word.casefold() not in {item.casefold() for item in result}:
                result.append(word)
        return result[:20]

    def _source_hash(self, snapshot: RepositorySnapshot, path: str) -> str | None:
        try:
            result = self.reader.read_file(snapshot.root_path, path)
        except (OSError, ValueError, RepositoryReadError):
            return None
        if result.truncated:
            return None
        return sha256(result.content.encode()).hexdigest()

    def _safe_memory_text(self, text: str) -> str:
        return redact_memory_text(text, [self.runtime.settings.llm_api_key or ""])
