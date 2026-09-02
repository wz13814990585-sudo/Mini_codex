from pathlib import Path

from tools.base import BaseTool


class ReadFileTool(BaseTool):

    name = "read_file"

    description = (
        "Read the contents of a text file from the current project."
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Relative path of the file to read."
                )
            }
        },
        "required": ["path"]
    }

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def execute(self, path: str) -> str:
        file_path = (
            self.workspace / path
        ).resolve()

        if (
            self.workspace not in file_path.parents
            and file_path != self.workspace
        ):
            raise ValueError(
                "Access outside the workspace is not allowed."
            )

        if not file_path.exists():
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        if not file_path.is_file():
            raise ValueError(
                f"Path is not a file: {path}"
            )

        return file_path.read_text(
            encoding="utf-8"
        )