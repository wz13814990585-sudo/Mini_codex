from ..base import BaseTool
from ..results import ToolResult


class ReplanTool(BaseTool):

    name = "replan"
    capabilities = frozenset({"plan.control"})

    description = (
        "当当前计划因新证据、意外的项目结构、假设失败或阻塞问题"
        "而不再合适时，请求修订实现计划。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "清楚说明为什么需要修订当前计划。"
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
                "重新规划请求已完成。",
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
