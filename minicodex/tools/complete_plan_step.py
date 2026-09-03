from minicodex.tools.base import BaseTool


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
        "required": []
    }

    def __init__(self, callback):
        self.callback = callback

    def execute(self) -> str:
        return self.callback()
