"""Patch application tools."""

from pathlib import Path

from .base import BaseTool
from .paths import resolve_workspace_path
from .results import ToolResult


class PatchFileTool(BaseTool):

    name = "patch_file"

    description = (
        "Replace an exact block of text inside an existing project file. "
        "Use this for small or targeted code modifications instead of "
        "rewriting the entire file."
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path of the file to modify.",
            },
            "old_text": {
                "type": "string",
                "description": (
                    "Exact existing text that should be replaced."
                ),
            },
            "new_text": {
                "type": "string",
                "description": (
                    "New text that should replace old_text."
                ),
            },
        },
        "required": [
            "path",
            "old_text",
            "new_text",
        ],
    }

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def execute(
        self,
        path: str,
        old_text: str,
        new_text: str,
    ) -> ToolResult:

        file_path = resolve_workspace_path(
            self.workspace,
            path,
        )

        if not file_path.exists():
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        content = file_path.read_text(
            encoding="utf-8"
        )

        count = content.count(old_text)

        if count == 0:
            raise ValueError(
                "old_text was not found in the file."
            )

        if count > 1:
            raise ValueError(
                "old_text appears multiple times. "
                "Provide a more specific code block."
            )

        updated_content = content.replace(
            old_text,
            new_text,
            1,
        )

        file_path.write_text(
            updated_content,
            encoding="utf-8",
        )

        return ToolResult(
            success=True,
            summary=(
                f"Successfully patched file: {path}"
            ),
            data={
                "path": path,
                "replacement_count": 1,
            },
        )