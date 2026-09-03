from pathlib import Path

from minicodex.tools.base import BaseTool
from minicodex.tools.paths import resolve_workspace_path


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
                )
            },
            "offset": {
                "type": "integer",
                "description": (
                    "1-based line number to start reading from. "
                    "Defaults to 1."
                )
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Maximum number of lines to return. "
                    "Defaults to 200."
                )
            }
        },
        "required": ["path"]
    }

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def execute(
        self,
        path: str,
        offset: int = 1,
        limit: int = DEFAULT_READ_LIMIT,
    ) -> str:
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

        start = max(int(offset), 1)
        max_lines = max(int(limit), 1)
        end = min(start + max_lines - 1, total)

        if total == 0:
            return f"# {path} lines 0-0 of 0\n"

        if start > total:
            return (
                f"# {path} lines {start}-{start - 1} of {total}\n"
                "# Offset is past the end of the file."
            )

        chunk = "\n".join(lines[start - 1:end])
        header = f"# {path} lines {start}-{end} of {total}"
        if end < total:
            header += (
                f"\n# Use offset={end + 1} to continue."
            )

        return f"{header}\n{chunk}"
