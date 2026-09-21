"""Read-only Git status tool."""

from ..base import BaseTool
from ..results import ToolResult

from ...agent.runtime import (
    GitAwareness,
)


class GitStatusTool(
    BaseTool,
):

    name = "git_status"
    capabilities = frozenset({"git.inspect"})

    description = (
        "查看当前 Git 仓库状态，包括分支、HEAD、是否有未提交更改、"
        "已暂存/已修改/已删除/未跟踪文件、任务开始时的变更，"
        "以及 MiniCodex 在当前任务中改动过的文件。"
    )

    parameters = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(
        self,
        awareness: GitAwareness,
    ):

        self.awareness = (
            awareness
        )

        self.workspace = (
            awareness.workspace
        )

    def execute(
        self,
    ) -> ToolResult:

        try:

            task_state = (
                self.awareness
                .refresh()
            )

        except Exception as e:

            return ToolResult(
                success=False,
                summary=(
                    "无法查看 Git 仓库状态。"
                ),
                data={
                    "failure_type": (
                        "git_status"
                    ),
                },
                error=(
                    f"{type(e).__name__}: "
                    f"{e}"
                ),
            )

        state = (
            task_state.current
        )

        if not (
            state.git_available
        ):

            return ToolResult(
                success=False,
                summary=(
                    "Git 不可用。"
                ),
                data=(
                    task_state
                    .to_dict()
                ),
                error=(
                    state.error
                    or "Git 可执行文件不可用。"
                ),
            )

        if not (
            state.is_repo
        ):

            return ToolResult(
                success=True,
                summary=(
                    "工作区不是 Git 仓库。"
                ),
                data=(
                    task_state
                    .to_dict()
                ),
                llm_content=(
                    self.awareness
                    .render()
                ),
            )

        return ToolResult(
            success=True,
            summary=(
                "已查看 Git 仓库状态。"
                f"分支={state.branch or 'detached'}，"
                f"有未提交更改={state.dirty}，"
                f"变更文件数="
                f"{len(state.changed_files)}。"
            ),
            data=(
                task_state
                .to_dict()
            ),
            llm_content=(
                self.awareness
                .render()
            ),
        )
