"""Scoped repository tree observation."""

from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from repopilot.agent.state import Observation
from repopilot.tools.base import ToolContext


class GetTreeInput(BaseModel):
    path: str = "."
    max_depth: int = Field(default=4, ge=1, le=20)
    max_entries: int = Field(default=500, ge=1, le=5_000)
    include_files: bool = True


class GetTreeTool:
    name = "get_tree"
    description = "List a repository directory or subtree without reading file contents."
    input_model: type[BaseModel] = GetTreeInput

    def execute(
        self,
        arguments: BaseModel,
        context: ToolContext,
        step_id: str,
    ) -> Observation:
        args = GetTreeInput.model_validate(arguments)
        scope = self._safe_scope(args.path)
        prefix = "" if scope == "." else f"{scope}/"
        entries: set[str] = set()
        for file in context.snapshot.files:
            path = file.relative_path
            if prefix and not path.startswith(prefix):
                continue
            relative = path[len(prefix) :] if prefix else path
            parts = PurePosixPath(relative).parts
            for depth in range(1, min(len(parts), args.max_depth) + 1):
                if depth == len(parts) and not args.include_files:
                    continue
                entry = "/".join(parts[:depth])
                if depth < len(parts):
                    entry += "/"
                entries.add(entry)

        ordered = sorted(entries)
        truncated = len(ordered) > args.max_entries
        selected = ordered[: args.max_entries]
        return Observation(
            step_id=step_id,
            tool_name=self.name,
            status="success",
            summary=f"Listed {len(selected)} entries under {scope}.",
            data={"root": scope, "tree": "\n".join(selected), "entry_count": len(selected)},
            truncated=truncated,
            truncation_notes=[f"Tree limited to {args.max_entries} entries."] if truncated else [],
        )

    @staticmethod
    def _safe_scope(path: str) -> str:
        normalized = PurePosixPath(path.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("Tree path must stay inside the repository root.")
        return normalized.as_posix()
