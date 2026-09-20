from pathlib import Path

from ..base import BaseTool
from ...utils.paths import resolve_workspace_path
from ..results import ToolResult


class ListFilesTool(BaseTool):
    capabilities = frozenset({"filesystem.read"})

    name = "list_files"

    description = (
        "列出当前项目中的文件与目录。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "要列出的相对目录路径。"
                    "使用 '.' 表示项目根目录。"
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
                f"目录未找到：{path}"
            )

        if not directory.is_dir():
            raise ValueError(
                f"路径不是目录：{path}"
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
                f"已在 '{path}' 下列出 "
                f"{len(entries)} 个条目。"
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
