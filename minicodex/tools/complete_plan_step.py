from .base import BaseTool
from .base import ToolResult


class CompletePlanStepTool(BaseTool):

    name = "complete_plan_step"

    description = (
        "Mark the current implementation plan step as completed. "
        "Call this only after the current step has actually "
        "been completed."
    )

    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, callback):
        self.callback = callback

    def execute(self) -> ToolResult:

        callback_result = self.callback()

        completed = bool(
            callback_result.get(
                "completed",
                False,
            )
        )

        message = str(
            callback_result.get(
                "message",
                "Plan step completion finished.",
            )
        )

        return ToolResult(
            success=True,
            summary=message,
            data={
                "completed": completed,
                "step_id": callback_result.get(
                    "step_id"
                ),
                "step_description": (
                    callback_result.get(
                        "step_description"
                    )
                ),
            },
        )