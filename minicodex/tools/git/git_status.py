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

    description = (
        "Inspect the current Git repository state, including "
        "branch, HEAD, dirty state, staged, modified, deleted, "
        "untracked files, task-start changes, and files touched "
        "by MiniCodex during the current task."
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
                    "Git repository state "
                    "could not be inspected."
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
                    "Git is unavailable."
                ),
                data=(
                    task_state
                    .to_dict()
                ),
                error=(
                    state.error
                    or "Git executable unavailable."
                ),
            )

        if not (
            state.is_repo
        ):

            return ToolResult(
                success=True,
                summary=(
                    "Workspace is not a "
                    "Git repository."
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
                "Git repository state inspected. "
                f"Branch={state.branch or 'detached'}, "
                f"dirty={state.dirty}, "
                f"changed_files="
                f"{len(state.changed_files)}."
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
