from pathlib import Path

from tools.base import BaseTool


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
                )
            },
            "content": {
                "type": "string",
                "description": (
                    "The complete text content that should be written "
                    "to the file."
                )
            }
        },
        "required": [
            "path",
            "content"
        ]
    }

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def execute(
        self,
        path: str,
        content: str
    ) -> str:

        file_path = (
            self.workspace / path
        ).resolve()

        # 防止写到 workspace 外
        if self.workspace not in file_path.parents \
                and file_path != self.workspace:

            raise ValueError(
                "Writing outside the workspace is not allowed."
            )

        # 如果父目录不存在，则自动创建
        file_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        file_path.write_text(
            content,
            encoding="utf-8"
        )

        return f"Successfully wrote file: {path}"