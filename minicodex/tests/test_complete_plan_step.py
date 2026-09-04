from ..tools.complete_plan_step import CompletePlanStepTool
from ..tools.base import ToolResult

def test_complete_plan_step_returns_structured_result():

    def callback():
        return {
            "completed": True,
            "step_id": 2,
            "step_description": "Implement parser",
            "message": (
                "Completed plan step 2: "
                "Implement parser"
            ),
        }

    tool = CompletePlanStepTool(
        callback=callback
    )

    result = tool.execute()

    assert result.success is True
    assert result.data["completed"] is True
    assert result.data["step_id"] == 2

def test_complete_plan_step_can_report_no_active_step():

    def callback():
        return {
            "completed": False,
            "step_id": None,
            "step_description": None,
            "message": "No active plan step.",
        }

    tool = CompletePlanStepTool(
        callback=callback
    )

    result = tool.execute()

    assert result.success is True
    assert result.data["completed"] is False