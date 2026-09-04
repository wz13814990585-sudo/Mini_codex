from .base import BaseTool
from .base import ToolResult


class ReplanTool(BaseTool):

    name = "replan"

    description = (
        "Request a revised implementation plan when the current "
        "plan is no longer appropriate because of new evidence, "
        "unexpected project structure, failed assumptions, or "
        "a blocking issue."
    )

    parameters = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "Explain clearly why the current plan "
                    "needs to be revised."
                ),
            }
        },
        "required": ["reason"],
    }

    def __init__(self, callback):
        self.callback = callback

    def execute(
        self,
        reason: str,
    ) -> ToolResult:

        callback_result = self.callback(
            reason
        )

        replanned = bool(
            callback_result.get(
                "replanned",
                False,
            )
        )

        message = str(
            callback_result.get(
                "message",
                "Replan request finished.",
            )
        )

        return ToolResult(
            success=True,
            summary=message,
            data={
                "replanned": replanned,
                "reason": callback_result.get(
                    "reason",
                    reason,
                ),
                "failure_reason": (
                    callback_result.get(
                        "failure_reason"
                    )
                ),
            },
        )