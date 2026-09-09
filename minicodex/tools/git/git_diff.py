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

    description = (
        "Inspect the current Git diff without modifying the "
        "repository. Can inspect the whole workspace or one "
        "specific path, and can inspect either unstaged or "
        "staged changes."
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Optional repository-relative path. "
                    "Omit to inspect the full diff."
                ),
            },
            "staged": {
                "type": "boolean",
                "description": (
                    "If true, inspect staged changes using "
                    "git diff --cached. Defaults to false."
                ),
                "default": False,
            },
            "max_chars": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50000,
                "description": (
                    "Maximum diff characters returned to the "
                    "LLM. Defaults to 12000."
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
                    "Git diff could not "
                    "be inspected."
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
                    "Git diff inspection failed."
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
            "staged"
            if diff.staged
            else "unstaged"
        )

        summary = (
            f"Git {diff_kind} diff inspected. "
            f"Characters={diff.total_chars}, "
            f"truncated={diff.truncated}."
        )

        llm_content = (
            diff.text
            if diff.text
            else (
                f"No {diff_kind} Git diff."
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
