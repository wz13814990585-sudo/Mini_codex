from pathlib import Path

from .base import BaseTool
from .paths import resolve_workspace_path
from .base import ToolResult


class ListFilesTool(BaseTool):

    name = "list_files"

    description = (
        "List files and directories inside the current project."
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Relative directory path to list. "
                    "Use '.' for the project root."
                ),
            }
        },
        "required": [],
    }

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def execute(
        self,
        path: str = ".",
    ) -> ToolResult:

        directory = resolve_workspace_path(
            self.workspace,
            path,
        )

        if not directory.exists():
            raise FileNotFoundError(
                f"Directory not found: {path}"
            )

        if not directory.is_dir():
            raise ValueError(
                f"Path is not a directory: {path}"
            )

        entries = []

        for item in sorted(
            directory.iterdir(),
            key=lambda item: item.name.lower(),
        ):

            relative_path = item.relative_to(
                self.workspace
            )

            if item.is_dir():
                entry_type = "directory"
            else:
                entry_type = "file"

            entries.append(
                {
                    "path": str(relative_path),
                    "type": entry_type,
                }
            )

        file_count = sum(
            entry["type"] == "file"
            for entry in entries
        )

        directory_count = sum(
            entry["type"] == "directory"
            for entry in entries
        )

        llm_lines = []

        for entry in entries:

            if entry["type"] == "directory":
                prefix = "[DIR] "
            else:
                prefix = "[FILE]"

            llm_lines.append(
                f"{prefix} {entry['path']}"
            )

        llm_content = "\n".join(
            llm_lines
        )

        return ToolResult(
            success=True,
            summary=(
                f"Listed {len(entries)} entries "
                f"in '{path}'."
            ),
            data={
                "path": path,
                "entry_count": len(entries),
                "file_count": file_count,
                "directory_count": directory_count,
                "entries": entries,
            },
            llm_content=llm_content,
        )