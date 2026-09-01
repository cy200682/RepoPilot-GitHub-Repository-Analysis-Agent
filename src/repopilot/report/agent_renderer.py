"""Markdown report renderer for Agent exploration results."""

from repopilot.agent.actions import AgentAnalysisResult, AgentFinding
from repopilot.agent.state import AgentState
from repopilot.models.repository import RepositorySnapshot


class AgentMarkdownReportRenderer:
    def render(
        self,
        analysis: AgentAnalysisResult,
        snapshot: RepositorySnapshot,
        state: AgentState,
        trace_path: str | None = None,
    ) -> str:
        sections = [
            "# Repository Analysis",
            "",
            f"> Repository: `{snapshot.source.owner}/{snapshot.source.name}`  ",
            f"> Commit: `{snapshot.commit_sha}`  ",
            f"> Agent status: `{state.status}`",
            "",
            "## 项目简介",
            "",
            analysis.project_summary,
            "",
            "## 技术栈",
            "",
            self._list(analysis.technology_stack),
            "",
            "## 项目目录",
            "",
            self._list(analysis.directory_overview),
            "",
            "## 程序入口",
            "",
            self._findings(analysis.entrypoints),
            "",
            "## 核心模块",
            "",
            self._findings(analysis.core_modules),
            "",
            "## 核心执行流程",
            "",
            self._ordered_findings(analysis.execution_flows),
            "",
            "## 模块关系",
            "",
            self._findings(analysis.module_relationships),
            "",
            "## 关键类 / 函数候选",
            "",
            self._list(analysis.key_symbols),
            "",
            "## 重要设计",
            "",
            self._list(analysis.important_designs),
            "",
            "## 潜在工程问题",
            "",
            self._list(analysis.engineering_risks),
            "",
            "## Evidence",
            "",
            self._evidence(analysis),
            "",
            "## 分析限制",
            "",
            self._list(analysis.limitations),
            "",
            "## 推荐源码阅读顺序",
            "",
            self._ordered(analysis.recommended_reading_order),
            "",
            "## Exploration Summary",
            "",
            f"- Goal: {state.goal}",
            f"- Iterations: {state.iteration_count}",
            f"- Tool calls: {state.tool_call_count}",
            f"- Files read: {len(state.visited_files)}",
            f"- Searches: {len(state.searched_queries)}",
            f"- AST files parsed: {len(state.ast_parsed_files)}",
            f"- AST nodes visited: {state.ast_node_count}",
            f"- Repository Map: {state.repository_map_node_count} nodes / "
            f"{state.repository_map_edge_count} edges",
            f"- Reference queries: {state.reference_query_count}",
            f"- Relationship queries: {state.relationship_query_count}",
            f"- Model requests: {state.llm_request_count}",
            f"- Prompt tokens: {state.prompt_tokens}",
            f"- Completion tokens: {state.completion_tokens}",
            f"- Total tokens: {state.total_tokens}"
            f"{' (estimated)' if state.token_usage_estimated else ''}",
            f"- Status: `{state.status}`",
            f"- Trace: `{trace_path or 'not exported'}`",
            "",
        ]
        return "\n".join(sections)

    @staticmethod
    def _list(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) or "- 暂无可靠结论。"

    @staticmethod
    def _ordered(items: list[str]) -> str:
        return "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1)) or "1. 暂无。"

    @staticmethod
    def _findings(items: list[AgentFinding]) -> str:
        return (
            "\n".join(
                f"- [{item.confidence}] {item.claim} — Evidence: "
                f"{', '.join(f'`{evidence_id}`' for evidence_id in item.evidence_ids)}"
                for item in items
            )
            or "- 暂无可靠结论。"
        )

    @staticmethod
    def _ordered_findings(items: list[AgentFinding]) -> str:
        return (
            "\n".join(
                f"{index}. [{item.confidence}] {item.claim} — Evidence: "
                f"{', '.join(f'`{evidence_id}`' for evidence_id in item.evidence_ids)}"
                for index, item in enumerate(items, 1)
            )
            or "1. 暂无。"
        )

    @staticmethod
    def _evidence(analysis: AgentAnalysisResult) -> str:
        if not analysis.evidence:
            return "- 当前报告没有可验证 Evidence。"
        lines = []
        for item in analysis.evidence:
            status = "verified" if item.verified else "unverified"
            lines.append(
                f"- `{item.evidence_id}` [{item.confidence}] {item.claim} — "
                f"`{item.path}:{item.start_line}-{item.end_line}` "
                f"(observation `{item.observation_id}`, source `{item.source_kind}`, "
                f"resolution `{item.resolution}`, {status})"
            )
        return "\n".join(lines)
