import json
from types import SimpleNamespace

import pytest

from agent.loop import run_agent_loop
from agent.progress import ProgressController
from agent.recovery import RecoveryController
from agent.replanner import Replanner
from agent.state import AgentPlan, PlanStep, StepStatus


def test_duplicate_tool_call_is_blocked_after_repeat_budget():
    progress = ProgressController(max_same_tool_repeats=2)

    assert progress.check_duplicate_tool_call(
        "read_file", {"path": "a.py"}
    )[0]
    assert progress.check_duplicate_tool_call(
        "read_file", {"path": "a.py"}
    )[0]

    allowed, reason = progress.check_duplicate_tool_call(
        "read_file", {"path": "a.py"}
    )

    assert not allowed
    assert "repeated" in reason.lower()


def test_read_test_cycle_without_edit_is_stalled():
    progress = ProgressController(progress_window=6)

    for tool_name in (
        "read_file",
        "run_tests",
        "search_code",
        "run_tests",
        "list_files",
        "run_command",
    ):
        progress.record_action(tool_name)

    assert progress.is_action_stalled()


def test_validation_improvement_and_stall_detection():
    progress = ProgressController(max_validation_no_progress=2)

    assert progress.track_validation("5 failed") == (True, None)
    assert progress.track_validation("3 failed") == (
        True,
        "Validation improved: 5 failed -> 3 failed.",
    )
    assert progress.track_validation("1 failed") == (
        True,
        "Validation improved: 3 failed -> 1 failed.",
    )

    progress.reset()
    assert progress.track_validation("3 failed") == (True, None)
    assert progress.track_validation("3 failed") == (True, None)
    validation_ok, message = progress.track_validation("3 failed")

    assert not validation_ok
    assert "not improving" in message.lower()


def test_first_successful_validation_reports_progress():
    progress = ProgressController()

    assert progress.track_validation("Exit code: 0") == (
        True,
        "Validation succeeded.",
    )


def test_recovery_ladder_and_progress_reset():
    recovery = RecoveryController(max_recovery_level=3)
    reasons = []

    warning, should_continue = recovery.recover(
        "first stall", reasons.append
    )
    assert should_continue
    assert "RECOVERY WARNING" in warning
    assert recovery.level == 1

    message, should_continue = recovery.recover(
        "second stall",
        lambda reason: (
            reasons.append(reason)
            or "Plan successfully revised. Continue."
        ),
    )
    assert should_continue
    assert "replanning succeeded" in message.lower()
    assert recovery.level == 2

    message, should_continue = recovery.recover(
        "third stall", reasons.append
    )
    assert not should_continue
    assert "remains stalled" in message.lower()
    assert recovery.level == 3

    recovery.mark_progress()
    assert recovery.level == 0


def test_replanner_preserves_completed_history():
    response = SimpleNamespace(
        content=json.dumps(
            {
                "goal": "Revised goal",
                "steps": [
                    "Previously completed",
                    "Implement revised remaining work",
                ],
            }
        )
    )
    llm = SimpleNamespace(
        chat=lambda **kwargs: response
    )
    plan = AgentPlan(
        goal="Original goal",
        completed_history=[
            PlanStep(
                id=1,
                description="Previously completed",
                status=StepStatus.COMPLETED,
            )
        ],
        steps=[
            PlanStep(
                id=2,
                description="Just completed",
                status=StepStatus.COMPLETED,
            ),
            PlanStep(
                id=3,
                description="No longer suitable",
                status=StepStatus.IN_PROGRESS,
            ),
        ],
    )

    revised = Replanner(llm).replan(
        user_request="Do the work",
        current_plan=plan,
        reason="New evidence",
    )

    assert [step.description for step in revised.completed_history] == [
        "Previously completed",
        "Just completed",
    ]
    assert [step.description for step in revised.steps] == [
        "Implement revised remaining work"
    ]
    assert revised.steps[0].id == 4


def test_successful_test_tool_resets_recovery_in_loop():
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="run_tests",
            arguments="{}",
        ),
    )

    class Response:
        def __init__(self, tool_calls, content=None):
            self.tool_calls = tool_calls
            self.content = content

        def model_dump(self, exclude_none=True):
            return {
                "role": "assistant",
                "tool_calls": self.tool_calls,
            }

    responses = iter(
        [
            Response([tool_call]),
            Response([], "done"),
        ]
    )
    recovery = RecoveryController()
    recovery.level = 2
    agent = SimpleNamespace(
        max_steps=2,
        max_step_attempts=5,
        active_plan=None,
        llm=SimpleNamespace(
            chat=lambda **kwargs: next(responses)
        ),
        registry=SimpleNamespace(
            get_schemas=lambda: [],
            execute=lambda name, arguments: "Exit code: 0",
        ),
        progress=ProgressController(),
        recovery=recovery,
        replan=lambda reason: "Plan successfully revised.",
        _build_system_prompt=lambda **kwargs: "system",
        _step_likely_requires_edit=lambda step: False,
    )

    assert run_agent_loop(agent, "request") == "done"
    assert recovery.level == 0


@pytest.mark.parametrize("level", [0, 4])
def test_recovery_level_configuration_is_validated(level):
    with pytest.raises(ValueError):
        RecoveryController(max_recovery_level=level)
