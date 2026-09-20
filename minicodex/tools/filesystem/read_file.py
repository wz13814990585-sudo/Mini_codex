from pathlib import Path

from ..base import BaseTool
from ...utils.paths import resolve_workspace_path
from ..results import ToolResult


DEFAULT_READ_LIMIT = 200


class ReadFileTool(BaseTool):

    name = "read_file"
    capabilities = frozenset({"filesystem.read", "file.read"})

    description = (
        "读取当前项目中文本文件的内容。"
        "默认最多返回 200 行；可用 offset/limit 继续阅读。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "要读取的文件相对路径。"
                ),
            },
            "offset": {
                "type": "integer",
                "description": (
                    "从第几行开始读取（从 1 起算）。"
                    "默认为 1。"
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    "最多返回的行数。"
                    "默认为 200。"
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
                f"文件未找到：{path}"
            )

        if not file_path.is_file():
            raise ValueError(
                f"路径不是文件：{path}"
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
                    f"已读取 {path}：文件为空。"
                ),
                data={
                    "path": path,
                    "start": 0,
                    "end": 0,
                    "total": 0,
                    "start_line": 0,
                    "end_line": 0,
                    "total_lines": 0,
                    "has_more": False,
                    "complete_file": True,
                    "next_offset": None,
                },
                llm_content="",
            )

        if start > total:
            return ToolResult(
                success=True,
                summary=(
                    f"已读取 {path}：起始行 {start} "
                    f"已超出文件末尾。"
                ),
                data={
                    "path": path,
                    "start": start,
                    "end": start - 1,
                    "total": total,
                    "start_line": start,
                    "end_line": start - 1,
                    "total_lines": total,
                    "has_more": False,
                    "complete_file": False,
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
                f"已读取 {path} "
                f"第 {start}-{end} 行"
                f"（共 {total} 行）。"
            ),
            data={
                "path": path,
                "start": start,
                "end": end,
                "total": total,
                "start_line": start,
                "end_line": end,
                "total_lines": total,
                "has_more": has_more,
                "complete_file": start == 1 and not has_more,
                "next_offset": next_offset,
            },
            llm_content=chunk,
        )
