from pathlib import Path

from minicodex.tools.base import BaseTool
from minicodex.tools.paths import resolve_workspace_path


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
                )
            }
        },
        "required": []
    }

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def execute(self, path: str = ".") -> str:

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

        for item in sorted(directory.iterdir()):

            relative_path = item.relative_to(
                self.workspace
            )

            if item.is_dir():
                entries.append(
                    f"[DIR]  {relative_path}"
                )
            else:
                entries.append(
                    f"[FILE] {relative_path}"
                )

        return "\n".join(entries)
