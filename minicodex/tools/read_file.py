from pathlib import Path

from .base import BaseTool
from .paths import resolve_workspace_path
from .results import ToolResult


DEFAULT_READ_LIMIT = 200


class ReadFileTool(BaseTool):

    name = "read_file"

    description = (
        "Read the contents of a text file from the current project. "
        "Defaults to at most 200 lines; use offset/limit to continue."
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Relative path of the file to read."
                ),
            },
            "offset": {
                "type": "integer",
                "description": (
                    "1-based line number to start reading from. "
                    "Defaults to 1."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Maximum number of lines to return. "
                    "Defaults to 200."
                ),
            },
        },
        "required": ["path"],
    }

    def __init__(
        self,
        workspace: str = ".",
    ):
        self.workspace = Path(
            workspace
        ).resolve()

    def execute(
        self,
        path: str,
        offset: int = 1,
        limit: int = DEFAULT_READ_LIMIT,
    ) -> ToolResult:

        file_path = resolve_workspace_path(
            self.workspace,
            path,
        )

        if not file_path.exists():
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        if not file_path.is_file():
            raise ValueError(
                f"Path is not a file: {path}"
            )

        content = file_path.read_text(
            encoding="utf-8"
        )

        lines = content.splitlines()
        total = len(lines)

        start = max(
            int(offset),
            1,
        )

        max_lines = max(
            int(limit),
            1,
        )

        if total == 0:
            return ToolResult(
                success=True,
                summary=(
                    f"Read {path}: file is empty."
                ),
                data={
                    "path": path,
                    "start_line": 0,
                    "end_line": 0,
                    "total_lines": 0,
                    "has_more": False,
                    "next_offset": None,
                },
                llm_content="",
            )

        if start > total:
            return ToolResult(
                success=True,
                summary=(
                    f"Read {path}: offset {start} "
                    f"is past the end of the file."
                ),
                data={
                    "path": path,
                    "start_line": start,
                    "end_line": start - 1,
                    "total_lines": total,
                    "has_more": False,
                    "next_offset": None,
                },
                llm_content="",
            )

        end = min(
            start + max_lines - 1,
            total,
        )

        chunk = "\n".join(
            lines[start - 1:end]
        )

        has_more = end < total

        next_offset = (
            end + 1
            if has_more
            else None
        )

        return ToolResult(
            success=True,
            summary=(
                f"Read {path} "
                f"lines {start}-{end} "
                f"of {total}."
            ),
            data={
                "path": path,
                "start_line": start,
                "end_line": end,
                "total_lines": total,
                "has_more": has_more,
                "next_offset": next_offset,
            },
            llm_content=chunk,
        )