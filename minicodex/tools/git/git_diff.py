"""Read-only Git diff tool."""

from ..base import BaseTool
from ..results import ToolResult

from ...agent.runtime import (
    GitRepositoryInspector,
)


class GitDiffTool(
    BaseTool,
):

    name = "git_diff"
    capabilities = frozenset({"git.inspect"})

    description = (
        "查看当前 Git diff，不会修改仓库。"
        "可查看整个工作区或指定路径，"
        "也可查看未暂存或已暂存的变更。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "可选的仓库相对路径。"
                    "省略则查看完整 diff。"
                ),
            },
            "staged": {
                "type": "boolean",
                "description": (
                    "若为 true，使用 git diff --cached "
                    "查看已暂存变更。默认为 false。"
                ),
                "default": False,
            },
            "max_chars": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50000,
                "description": (
                    "返回给模型的最大 diff 字符数。"
                    "默认为 12000。"
                ),
                "default": 12000,
            },
        },
        "additionalProperties": False,
    }

    def __init__(
        self,
        inspector: GitRepositoryInspector,
    ):

        self.inspector = (
            inspector
        )

        self.workspace = (
            inspector.workspace
        )

    def execute(
        self,
        path: str | None = None,
        staged: bool = False,
        max_chars: int = 12000,
    ) -> ToolResult:

        try:

            diff = (
                self.inspector
                .diff(
                    path=path,
                    staged=bool(
                        staged
                    ),
                    max_chars=int(
                        max_chars
                    ),
                )
            )

        except Exception as e:

            return ToolResult(
                success=False,
                summary=(
                    "无法查看 Git diff。"
                ),
                data={
                    "failure_type": (
                        "git_diff"
                    ),
                },
                error=(
                    f"{type(e).__name__}: "
                    f"{e}"
                ),
            )

        if not (
            diff.success
        ):

            return ToolResult(
                success=False,
                summary=(
                    "Git diff 查看失败。"
                ),
                data={
                    "staged": (
                        diff.staged
                    ),
                    "path": (
                        diff.path
                    ),
                    "total_chars": (
                        diff.total_chars
                    ),
                    "truncated": (
                        diff.truncated
                    ),
                    "failure_type": (
                        "git_diff"
                    ),
                },
                error=(
                    diff.error
                ),
            )

        diff_kind = (
            "已暂存"
            if diff.staged
            else "未暂存"
        )

        summary = (
            f"已查看 Git {diff_kind} diff。"
            f"字符数={diff.total_chars}，"
            f"已截断={diff.truncated}。"
        )

        llm_content = (
            diff.text
            if diff.text
            else (
                f"无 {diff_kind} Git diff。"
            )
        )

        return ToolResult(
            success=True,
            summary=summary,
            data={
                "staged": (
                    diff.staged
                ),
                "path": (
                    diff.path
                ),
                "total_chars": (
                    diff.total_chars
                ),
                "truncated": (
                    diff.truncated
                ),
            },
            llm_content=(
                llm_content
            ),
        )
