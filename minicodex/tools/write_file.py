from pathlib import Path

from .base import BaseTool
from .paths import resolve_workspace_path
from .results import ToolResult


class WriteFileTool(BaseTool):

    name = "write_file"

    description = (
        "Create a new text file or overwrite an existing text file "
        "inside the current project."
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Relative path of the file to write, "
                    "for example 'calculator.py'."
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "The complete text content that should be written "
                    "to the file."
                ),
            },
        },
        "required": [
            "path",
            "content",
        ],
    }

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def execute(
        self,
        path: str,
        content: str,
    ) -> ToolResult:

        file_path = resolve_workspace_path(
            self.workspace,
            path,
        )

        existed_before = file_path.exists()

        # 如果父目录不存在，则自动创建
        file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        file_path.write_text(
            content,
            encoding="utf-8",
        )

        if existed_before:
            summary = (
                f"Successfully overwrote file: {path}"
            )
        else:
            summary = (
                f"Successfully created file: {path}"
            )

        return ToolResult(
            success=True,
            summary=summary,
            data={
                "path": path,
                "created": not existed_before,
                "overwritten": existed_before,
                "chars_written": len(content),
            },
        )