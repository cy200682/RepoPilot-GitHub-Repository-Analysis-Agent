"""Render validated Phase 1 analysis into stable Markdown."""

from repopilot.models.analysis import AnalysisResult
from repopilot.models.repository import RepositorySnapshot


class MarkdownReportRenderer:
    """Render without making new repository claims."""

    def render(
        self,
        result: AnalysisResult,
        snapshot: RepositorySnapshot,
        context_truncation_notes: list[str] | None = None,
    ) -> str:
        sections = [
            "# Repository Analysis",
            "",
            f"> Repository: `{snapshot.source.owner}/{snapshot.source.name}`  ",
            f"> Commit: `{snapshot.commit_sha}`",
            "",
            "## 项目简介",
            "",
            result.project_summary,
            "",
            "## 技术栈",
            "",
            self._list(result.technology_stack),
            "",
            "## 项目目录",
            "",
            "```text",
            snapshot.directory_tree,
            "```",
            "",
            self._list(result.directory_overview),
            "",
            "## 程序入口候选",
            "",
            self._list(result.entrypoint_candidates),
            "",
            "## 核心模块候选",
            "",
            self._list(result.core_module_candidates),
            "",
            "## Evidence",
            "",
            self._evidence(result),
            "",
            "## 已读取的关键文件",
            "",
            self._read_files(snapshot),
            "",
            "## 分析限制",
            "",
            self._limitations(result, snapshot, context_truncation_notes or []),
            "",
            "## 推荐源码阅读顺序",
            "",
            self._ordered_list(result.recommended_reading_order),
            "",
        ]
        return "\n".join(sections)

    @staticmethod
    def _list(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- 暂无可靠结论。"

    @staticmethod
    def _ordered_list(items: list[str]) -> str:
        return "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1)) or "1. 暂无。"

    @staticmethod
    def _evidence(result: AnalysisResult) -> str:
        if not result.evidence:
            return "- 当前结果没有可验证的源码引用。"
        lines = []
        for item in result.evidence:
            status = "verified" if item.verified else "unverified"
            location = item.path
            if item.start_line:
                location += f":{item.start_line}"
                if item.end_line:
                    location += f"-{item.end_line}"
            lines.append(f"- {item.claim} — `{location}` ({status})")
        return "\n".join(lines)

    @staticmethod
    def _read_files(snapshot: RepositorySnapshot) -> str:
        paths: list[str] = []
        if snapshot.readme_path:
            paths.append(snapshot.readme_path)
        paths.extend(snapshot.dependency_contents)
        paths.extend(snapshot.config_contents)
        paths.extend(candidate.path for candidate in snapshot.entrypoint_candidates[:5])
        unique = list(dict.fromkeys(paths))
        return "\n".join(f"- `{path}`" for path in unique) or "- 未读取文件内容。"

    @staticmethod
    def _limitations(
        result: AnalysisResult,
        snapshot: RepositorySnapshot,
        context_truncation_notes: list[str],
    ) -> str:
        limitations = list(result.limitations)
        limitations.extend(snapshot.truncation_notes)
        limitations.extend(context_truncation_notes)
        limitations.append("Phase 1 使用有限上下文；入口和核心模块均为候选结论。")
        return "\n".join(f"- {item}" for item in dict.fromkeys(limitations))
