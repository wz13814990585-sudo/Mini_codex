from minicodex.tools.base import BaseTool


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
                )
            }
        },
        "required": ["reason"]
    }

    def __init__(self, callback):
        self.callback = callback

    def execute(self, reason: str) -> str:
        return self.callback(reason)
