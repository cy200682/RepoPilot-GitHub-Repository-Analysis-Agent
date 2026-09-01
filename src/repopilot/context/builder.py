"""Build a transparent, bounded Phase 1 analysis context."""

from __future__ import annotations

from repopilot.config import Settings
from repopilot.exceptions import RepositoryReadError
from repopilot.models.analysis import AnalysisRequest
from repopilot.models.repository import RepositorySnapshot
from repopilot.repository.reader import RepositoryReader, RepositoryReaderProtocol


class ContextBuilder:
    """Select high-value repository facts under a character budget."""

    def __init__(
        self,
        settings: Settings,
        reader: RepositoryReaderProtocol | None = None,
    ) -> None:
        self.settings = settings
        self.reader = reader or RepositoryReader(settings)

    def build(self, snapshot: RepositorySnapshot) -> AnalysisRequest:
        sections: list[tuple[str, str]] = [
            (
                "Repository metadata",
                (
                    f"Name: {snapshot.source.owner}/{snapshot.source.name}\n"
                    f"Commit: {snapshot.commit_sha}\n"
                    f"Files: {snapshot.stats.total_files}\n"
                    f"Bytes: {snapshot.stats.total_bytes}"
                ),
            ),
            ("Directory tree", snapshot.directory_tree),
        ]

        deterministic_facts = self._format_deterministic_facts(snapshot)
        if deterministic_facts:
            sections.append(("Deterministic scan findings", deterministic_facts))

        if snapshot.readme_content:
            sections.append(
                (
                    f"README ({snapshot.readme_path})",
                    snapshot.readme_content,
                )
            )
        entrypoint_contents, read_notes = self._read_entrypoint_candidates(snapshot)
        if entrypoint_contents:
            sections.append(("Entrypoint candidate excerpts", entrypoint_contents))

        if snapshot.dependency_contents:
            sections.append(
                (
                    "Dependency files",
                    self._format_files(snapshot.dependency_contents),
                )
            )
        if snapshot.config_contents:
            sections.append(("Configuration files", self._format_files(snapshot.config_contents)))

        context, fit_notes = self._fit_sections(sections)
        truncation_notes = read_notes + fit_notes
        return AnalysisRequest(
            repository_name=f"{snapshot.source.owner}/{snapshot.source.name}",
            commit_sha=snapshot.commit_sha,
            context=context,
            truncated=bool(truncation_notes or snapshot.truncation_notes),
            truncation_notes=truncation_notes,
        )

    @staticmethod
    def _format_files(contents: dict[str, str]) -> str:
        return "\n\n".join(f"--- {path} ---\n{content}" for path, content in contents.items())

    @staticmethod
    def _format_deterministic_facts(snapshot: RepositorySnapshot) -> str:
        lines: list[str] = []
        for language in snapshot.detected_languages:
            lines.append(f"Language: {language.name} ({language.evidence})")
        for framework in snapshot.detected_frameworks:
            lines.append(f"Framework/library: {framework.name} ({framework.evidence})")
        for candidate in snapshot.entrypoint_candidates:
            lines.append(f"Entrypoint candidate: {candidate.path} ({candidate.reason})")
        for note in snapshot.truncation_notes:
            lines.append(f"Scan limitation: {note}")
        return "\n".join(lines)

    def _read_entrypoint_candidates(
        self,
        snapshot: RepositorySnapshot,
    ) -> tuple[str, list[str]]:
        excerpts: list[str] = []
        notes: list[str] = []
        per_file_limit = min(8_000, self.settings.max_file_bytes)
        for candidate in snapshot.entrypoint_candidates[:5]:
            try:
                read_result = self.reader.read_file(
                    snapshot.root_path,
                    candidate.path,
                    max_bytes=per_file_limit,
                )
                excerpts.append(
                    f"--- {candidate.path} ({candidate.reason}) ---\n{read_result.content}"
                )
                if read_result.truncated:
                    notes.append(
                        f"Entrypoint excerpt {candidate.path} was truncated to "
                        f"{read_result.bytes_read} bytes."
                    )
            except RepositoryReadError as exc:
                notes.append(str(exc))
        return "\n\n".join(excerpts), notes

    def _fit_sections(self, sections: list[tuple[str, str]]) -> tuple[str, list[str]]:
        budget = self.settings.context_char_budget
        chunks: list[str] = []
        used = 0
        notes: list[str] = []

        for index, (title, content) in enumerate(sections):
            prefix = f"\n## {title}\n"
            available = budget - used - len(prefix)
            if available <= 0:
                omitted = ", ".join(section_title for section_title, _ in sections[index:])
                notes.append(f"Context budget omitted sections: {omitted}.")
                break
            selected = content
            if len(selected) > available:
                selected = selected[:available]
                notes.append(
                    f"Context section {title} was truncated from "
                    f"{len(content)} to {len(selected)} characters."
                )
            chunk = prefix + selected
            chunks.append(chunk)
            used += len(chunk)
            if len(selected) < len(content):
                omitted_titles = [section_title for section_title, _ in sections[index + 1 :]]
                if omitted_titles:
                    notes.append(f"Context budget omitted sections: {', '.join(omitted_titles)}.")
                break

        return "".join(chunks).lstrip(), notes
