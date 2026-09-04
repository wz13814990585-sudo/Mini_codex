from ..tools.replan import ReplanTool
from ..tools.base import ToolResult

def test_replan_returns_structured_success():

    def callback(reason):
        return {
            "replanned": True,
            "reason": reason,
            "failure_reason": None,
            "message": (
                "Plan successfully revised."
            ),
        }

    tool = ReplanTool(
        callback=callback
    )

    result = tool.execute(
        reason="New repository evidence."
    )

    assert result.success is True
    assert result.data["replanned"] is True

    assert (
        result.data["reason"]
        == "New repository evidence."
    )

    assert (
        result.data["failure_reason"]
        is None
    )

def test_replan_can_report_not_replanned():

    def callback(reason):
        return {
            "replanned": False,
            "reason": reason,
            "failure_reason": (
                "No replanner configured."
            ),
            "message": (
                "No replanner configured."
            ),
        }

    tool = ReplanTool(
        callback=callback
    )

    result = tool.execute(
        reason="Current plan is blocked."
    )

    assert result.success is True

    assert (
        result.data["replanned"]
        is False
    )

    assert (
        result.data["failure_reason"]
        == "No replanner configured."
    )