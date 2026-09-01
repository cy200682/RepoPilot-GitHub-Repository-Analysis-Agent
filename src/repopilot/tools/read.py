"""Line-addressable read_file Agent tool."""

from pydantic import BaseModel, Field

from repopilot.agent.state import EvidenceLocation, Observation
from repopilot.config import Settings
from repopilot.tools.base import ToolContext


class ReadFileInput(BaseModel):
    path: str
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    max_chars: int | None = Field(default=None, ge=100)


class ReadFileTool:
    name = "read_file"
    description = "Read a safe repository-relative text file range with line numbers."
    input_model: type[BaseModel] = ReadFileInput

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(
        self,
        arguments: BaseModel,
        context: ToolContext,
        step_id: str,
    ) -> Observation:
        args = ReadFileInput.model_validate(arguments)
        if args.end_line is not None and args.end_line < args.start_line:
            raise ValueError("end_line must be greater than or equal to start_line.")
        requested_end = args.end_line or (args.start_line + self.settings.tool_max_read_lines - 1)
        end_line = min(requested_end, args.start_line + self.settings.tool_max_read_lines - 1)
        char_limit = min(
            args.max_chars or self.settings.tool_max_read_chars,
            self.settings.tool_max_read_chars,
        )
        read_result = context.reader.read_file(context.root_path, args.path)
        lines = read_result.content.splitlines()
        if args.start_line > max(len(lines), 1):
            raise ValueError(f"start_line exceeds file length ({len(lines)} lines).")
        selected_lines = lines[args.start_line - 1 : end_line]
        numbered = "\n".join(
            f"{number}: {line}" for number, line in enumerate(selected_lines, start=args.start_line)
        )
        char_truncated = len(numbered) > char_limit
        if char_truncated:
            numbered = numbered[:char_limit].rsplit("\n", 1)[0]
        actual_end = args.start_line + max(len(numbered.splitlines()) - 1, 0)
        truncated = (
            char_truncated
            or read_result.truncated
            or end_line < requested_end
            or actual_end < len(lines)
        )
        notes: list[str] = []
        if char_truncated:
            notes.append(f"Output limited to {char_limit} characters.")
        if read_result.truncated:
            notes.append("Underlying file read reached the configured byte limit.")
        if end_line < requested_end:
            notes.append(f"Read limited to {self.settings.tool_max_read_lines} lines.")
        return Observation(
            step_id=step_id,
            tool_name=self.name,
            status="success",
            summary=f"Read {args.path}:{args.start_line}-{actual_end}.",
            data={
                "path": args.path,
                "start_line": args.start_line,
                "end_line": actual_end,
                "total_lines": len(lines),
                "content": numbered,
            },
            evidence_locations=[
                EvidenceLocation(path=args.path, start_line=args.start_line, end_line=actual_end)
            ],
            truncated=truncated,
            truncation_notes=notes,
        )
