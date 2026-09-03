import json
from types import SimpleNamespace

import pytest

from minicodex.agent.context import (
    compact_messages,
    summarize_tool_result,
)
from minicodex.agent.loop import run_agent_loop
from minicodex.agent.progress import (
    ProgressController,
    ValidationStatus,
)
from minicodex.agent.recovery import RecoveryController
from minicodex.agent.replanner import Replanner
from minicodex.agent.state import AgentPlan, PlanStep, StepStatus
from minicodex.tools.read_file import ReadFileTool
from minicodex.tools.run_tests import compact_pytest_output
from minicodex.tools.search_code import SearchCodeTool


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

    progress = ProgressController(
        max_validation_no_progress=2
    )

    # =========================================
    # Initial result
    # =========================================

    result = progress.track_validation(
        "5 failed"
    )

    assert (
        result.status
        == ValidationStatus.UNKNOWN
    )

    assert result.current_failed == 5
    assert not result.stalled

    # =========================================
    # Improved
    # =========================================

    result = progress.track_validation(
        "3 failed"
    )

    assert (
        result.status
        == ValidationStatus.IMPROVED
    )

    assert result.previous_failed == 5
    assert result.current_failed == 3
    assert result.meaningful_progress

    # =========================================
    # Improved Again
    # =========================================

    result = progress.track_validation(
        "1 failed"
    )

    assert (
        result.status
        == ValidationStatus.IMPROVED
    )

    assert result.previous_failed == 3
    assert result.current_failed == 1

    # =========================================
    # Reset
    # =========================================

    progress.reset()

    progress.track_validation(
        "3 failed"
    )

    # First unchanged result
    result = progress.track_validation(
        "3 failed"
    )

    assert (
        result.status
        == ValidationStatus.UNCHANGED
    )

    assert not result.stalled

    # Second unchanged result
    result = progress.track_validation(
        "3 failed"
    )

    assert (
        result.status
        == ValidationStatus.UNCHANGED
    )

    assert result.stalled

def test_validation_regression_is_detected():

    progress = ProgressController(
        max_validation_no_progress=2
    )

    progress.track_validation(
        "2 failed"
    )

    result = progress.track_validation(
        "5 failed"
    )

    assert (
        result.status
        == ValidationStatus.REGRESSED
    )

    assert result.previous_failed == 2
    assert result.current_failed == 5

    assert not result.meaningful_progress

    assert (
        "regressed"
        in result.message.lower()
    )

def test_successful_edit_is_not_meaningful_progress():

    recovery = RecoveryController()

    # Agent 已经进入 Level 1 Recovery
    recovery.level = 1

    # 模拟 patch_file 成功
    result = (
        "File successfully patched."
    )

    assert (
        "successfully"
        in result.lower()
    )

    # 关键：
    # 我们没有调用 recovery.mark_progress()

    assert recovery.level == 1


def test_first_successful_validation_reports_progress():
    progress = ProgressController()

    result = progress.track_validation("Exit code: 0")

    assert result.status == ValidationStatus.PASSED
    assert result.meaningful_progress
    assert result.current_failed == 0
    assert result.message == "Validation succeeded."


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


def test_successful_tool_round_does_not_consume_step_failure_budget():
    step = PlanStep(id=1, description="Inspect implementation")
    plan = AgentPlan(goal="Inspect", steps=[step])
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="read_file",
            arguments='{"path": "example.py"}',
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
    agent = SimpleNamespace(
        max_steps=2,
        max_step_attempts=1,
        active_plan=plan,
        llm=SimpleNamespace(
            chat=lambda **kwargs: next(responses)
        ),
        registry=SimpleNamespace(
            get_schemas=lambda: [],
            execute=lambda name, arguments: "file contents",
        ),
        progress=ProgressController(),
        recovery=RecoveryController(),
        replan=lambda reason: "Plan successfully revised.",
        _build_system_prompt=lambda **kwargs: "system",
        _step_likely_requires_edit=lambda current_step: False,
    )

    result = run_agent_loop(agent, "request")
    assert "done" in result
    assert step.attempts == 0


def test_failed_tool_call_consumes_step_failure_budget():
    step = PlanStep(id=1, description="Modify implementation")
    plan = AgentPlan(goal="Modify", steps=[step])
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="patch_file",
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

    def fail_tool(name, arguments):
        raise ValueError("invalid patch")

    agent = SimpleNamespace(
        max_steps=2,
        max_step_attempts=2,
        active_plan=plan,
        llm=SimpleNamespace(
            chat=lambda **kwargs: next(responses)
        ),
        registry=SimpleNamespace(
            get_schemas=lambda: [],
            execute=fail_tool,
        ),
        progress=ProgressController(),
        recovery=RecoveryController(),
        replan=lambda reason: "Plan successfully revised.",
        _build_system_prompt=lambda **kwargs: "system",
        _step_likely_requires_edit=lambda current_step: False,
    )

    result = run_agent_loop(agent, "request")
    assert "done" in result
    assert step.attempts == 1


@pytest.mark.parametrize("level", [0, 4])
def test_recovery_level_configuration_is_validated(level):
    with pytest.raises(ValueError):
        RecoveryController(max_recovery_level=level)


def test_complete_current_step_moves_to_history():
    step1 = PlanStep(id=1, description="A")
    step2 = PlanStep(id=2, description="B")
    plan = AgentPlan(goal="g", steps=[step1, step2])

    plan.start_current_step()
    completed = plan.complete_current_step()

    assert completed is step1
    assert step1.status == StepStatus.COMPLETED
    assert plan.completed_history == [step1]
    assert plan.steps == [step2]
    assert not plan.is_completed()

    plan.start_current_step()
    plan.complete_current_step()

    assert plan.is_completed()
    assert plan.get_current_step() is None
    assert plan.steps == []
    assert plan.completed_history == [step1, step2]


def test_failed_plan_step_is_not_completed():
    step = PlanStep(id=1, description="A")
    plan = AgentPlan(goal="g", steps=[step])
    plan.start_current_step()
    plan.fail_current_step()

    assert step.status == StepStatus.FAILED
    assert not plan.is_completed()
    assert plan.get_current_step() is None


def test_completing_plan_step_resets_progress_and_recovery():
    from minicodex.agent.agent import MiniCodexAgent

    step1 = PlanStep(id=1, description="Edit code")
    step2 = PlanStep(id=2, description="Run tests")
    plan = AgentPlan(goal="g", steps=[step1, step2])
    plan.start_current_step()

    agent = MiniCodexAgent(
        llm=SimpleNamespace(),
        registry=SimpleNamespace(),
    )
    agent.active_plan = plan
    agent.recovery.level = 2
    agent.progress.last_tool_signature = ("read_file", "{}")
    agent.progress.same_tool_repeat_count = 2
    for _ in range(6):
        agent.progress.record_action("read_file")

    result = agent.complete_plan_step()

    assert "Completed plan step 1" in result
    assert agent.recovery.level == 0
    assert agent.progress.recent_actions == []
    assert agent.progress.last_tool_signature is None
    assert plan.completed_history == [step1]
    assert plan.steps == [step2]


def test_edit_detection_uses_word_boundaries_and_chinese_rewrite():
    from minicodex.agent.agent import MiniCodexAgent

    inspect = PlanStep(id=1, description="Read additional files")
    rewrite = PlanStep(id=2, description="新建/重写测试文件")
    implement = PlanStep(id=3, description="implement the merge")

    assert not MiniCodexAgent._step_likely_requires_edit(None, inspect)
    assert MiniCodexAgent._step_likely_requires_edit(None, rewrite)
    assert MiniCodexAgent._step_likely_requires_edit(None, implement)


def test_pipeline_exit_code_does_not_hide_failed_tests():
    progress = ProgressController()

    result = progress.track_validation(
        "Exit code: 0\n"
        "STDOUT:\n"
        "FAILED test_foo\n"
        "1 failed, 38 passed in 0.13s\n"
    )

    assert result.current_failed == 1
    assert result.status == ValidationStatus.UNKNOWN


def test_failed_token_without_summary_is_not_treated_as_pass():
    progress = ProgressController()

    result = progress.track_validation(
        "Exit code: 0\n"
        "STDOUT:\n"
        "E         Use -v to get more diff\n"
        "FAILED minicodex/tests/test_foo.py::test_bar\n"
    )

    assert result.status == ValidationStatus.UNKNOWN
    assert result.current_failed is None
    assert progress.last_validation_failed_count is None


class _LoopResponse:
    def __init__(self, tool_calls, content=None):
        self.tool_calls = tool_calls
        self.content = content

    def model_dump(self, exclude_none=True):
        return {
            "role": "assistant",
            "tool_calls": self.tool_calls,
        }


def test_run_command_pytest_resets_recovery_in_loop():
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="run_command",
            arguments='{"command": "pytest minicodex/tests/test_merge_fixture.py -q"}',
        ),
    )
    responses = iter(
        [
            _LoopResponse([tool_call]),
            _LoopResponse([], "done"),
        ]
    )
    recovery = RecoveryController()
    recovery.level = 2
    agent = SimpleNamespace(
        max_steps=2,
        max_step_attempts=5,
        active_plan=None,
        llm=SimpleNamespace(chat=lambda **kwargs: next(responses)),
        registry=SimpleNamespace(
            get_schemas=lambda: [],
            execute=lambda name, arguments: (
                "Exit code: 0\nSTDOUT:\n39 passed in 0.13s\n"
            ),
        ),
        progress=ProgressController(),
        recovery=recovery,
        replan=lambda reason: "Plan successfully revised.",
        _build_system_prompt=lambda **kwargs: "system",
        _step_likely_requires_edit=lambda step: False,
    )

    assert run_agent_loop(agent, "request") == "done"
    assert recovery.level == 0
    assert agent.progress.last_validation_failed_count == 0


def test_max_steps_stop_reports_plan_and_passed_tests():
    step = PlanStep(id=1, description="Rewrite tests")
    plan = AgentPlan(goal="Replace merge", steps=[step])
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="run_tests",
            arguments="{}",
        ),
    )
    responses = iter([_LoopResponse([tool_call])])
    agent = SimpleNamespace(
        max_steps=1,
        max_step_attempts=5,
        active_plan=plan,
        llm=SimpleNamespace(chat=lambda **kwargs: next(responses)),
        registry=SimpleNamespace(
            get_schemas=lambda: [],
            execute=lambda name, arguments: (
                "Exit code: 0\nSTDOUT:\n39 passed in 0.13s\n"
            ),
        ),
        progress=ProgressController(),
        recovery=RecoveryController(),
        replan=lambda reason: "Plan successfully revised.",
        _build_system_prompt=lambda **kwargs: "system",
        _step_likely_requires_edit=lambda step: False,
    )

    result = run_agent_loop(agent, "request")

    assert "maximum number of agent steps" in result.lower()
    assert "tests passed" in result.lower()
    assert "1 remaining" in result
    assert "Rewrite tests" in result


def test_incomplete_plan_continues_while_budget_remains():
    step = PlanStep(id=1, description="Implement merge")
    plan = AgentPlan(goal="Replace merge", steps=[step])
    chat_calls = []
    responses = iter(
        [
            _LoopResponse([], "I think I'm done"),
            _LoopResponse([], "still stopping"),
        ]
    )

    def chat(**kwargs):
        chat_calls.append(kwargs["messages"])
        return next(responses)

    agent = SimpleNamespace(
        max_steps=2,
        max_step_attempts=5,
        active_plan=plan,
        llm=SimpleNamespace(chat=chat),
        registry=SimpleNamespace(
            get_schemas=lambda: [],
            execute=lambda name, arguments: "",
        ),
        progress=ProgressController(),
        recovery=RecoveryController(),
        replan=lambda reason: "Plan successfully revised.",
        _build_system_prompt=lambda **kwargs: "system",
        _step_likely_requires_edit=lambda step: False,
    )

    result = run_agent_loop(agent, "request")

    assert len(chat_calls) == 2
    reminder = chat_calls[1][-1]["content"]
    assert "plan is not finished" in reminder.lower()
    assert "unfinished" in result.lower()
    assert "still stopping" in result


def test_step_attempt_budget_is_inclusive():
    step = PlanStep(id=1, description="Modify implementation")
    plan = AgentPlan(goal="Modify", steps=[step])
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="patch_file",
            arguments="{}",
        ),
    )
    responses = iter(
        [
            _LoopResponse([tool_call]),
            _LoopResponse([], "recovered"),
        ]
    )
    recovery = RecoveryController()

    def fail_tool(name, arguments):
        raise ValueError("invalid patch")

    agent = SimpleNamespace(
        max_steps=2,
        max_step_attempts=1,
        active_plan=plan,
        llm=SimpleNamespace(chat=lambda **kwargs: next(responses)),
        registry=SimpleNamespace(
            get_schemas=lambda: [],
            execute=fail_tool,
        ),
        progress=ProgressController(),
        recovery=recovery,
        replan=lambda reason: "Plan successfully revised.",
        _build_system_prompt=lambda **kwargs: "system",
        _step_likely_requires_edit=lambda current_step: False,
    )

    result = run_agent_loop(agent, "request")

    assert recovery.level == 1
    assert "recovered" in result


def test_planner_caps_step_count_to_agent_budget():
    from minicodex.agent.planner import Planner

    response = SimpleNamespace(
        content=json.dumps(
            {
                "goal": "Do the work",
                "steps": [f"step {i}" for i in range(1, 12)],
            }
        )
    )
    planner = Planner(
        SimpleNamespace(chat=lambda **kwargs: response)
    )

    plan = planner.create_plan("do it", max_agent_steps=20)

    assert len(plan.steps) == 6
    assert plan.steps[-1].description == "step 6"


def test_compact_messages_summarizes_old_tool_bodies():
    long_body = "line\n" * 200
    messages = [
        {"role": "user", "content": "do the task"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "old.py"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": long_body},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c2",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "mid.py"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c2", "content": "recent mid"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c3",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "new.py"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c3", "content": "latest full body"},
    ]

    compact_messages(messages)

    assert messages[0]["content"] == "do the task"
    assert messages[2]["content"].startswith("[read_file] old.py")
    assert "lines" in messages[2]["content"]
    assert messages[4]["content"] == "recent mid"
    assert messages[6]["content"] == "latest full body"


def test_compact_messages_omits_old_write_file_content():
    payload = "x" * 900
    messages = [
        {"role": "user", "content": "write files"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "w1",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps(
                            {"path": "a.py", "content": payload}
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "w1",
            "content": "Successfully wrote file: a.py",
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "w2",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps(
                            {"path": "b.py", "content": payload}
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "w2",
            "content": "Successfully wrote file: b.py",
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "w3",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps(
                            {"path": "c.py", "content": payload}
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "w3",
            "content": "Successfully wrote file: c.py",
        },
    ]

    compact_messages(messages)

    old_args = json.loads(
        messages[1]["tool_calls"][0]["function"]["arguments"]
    )
    recent_args = json.loads(
        messages[5]["tool_calls"][0]["function"]["arguments"]
    )

    assert payload not in old_args["content"]
    assert old_args["content"].startswith("[omitted,")
    assert recent_args["content"] == payload


def test_old_write_file_content_is_omitted_from_later_llm_requests():
    payload = "x" * 900
    chat_calls = []
    round_id = {"n": 0}

    def chat(**kwargs):
        chat_calls.append(kwargs["messages"])
        n = round_id["n"]
        round_id["n"] += 1
        if n < 3:
            tool_call = SimpleNamespace(
                id=f"call-{n}",
                function=SimpleNamespace(
                    name="write_file",
                    arguments=json.dumps(
                        {"path": f"{n}.py", "content": payload}
                    ),
                ),
            )
            return _LoopResponse([tool_call])
        return _LoopResponse([], "done")

    agent = SimpleNamespace(
        max_steps=4,
        max_step_attempts=5,
        active_plan=None,
        llm=SimpleNamespace(chat=chat),
        registry=SimpleNamespace(
            get_schemas=lambda: [],
            execute=lambda name, arguments: (
                "Successfully wrote file: x.py"
            ),
        ),
        progress=ProgressController(),
        recovery=RecoveryController(),
        replan=lambda reason: "Plan successfully revised.",
        _build_system_prompt=lambda **kwargs: "system",
        _step_likely_requires_edit=lambda step: False,
    )

    assert run_agent_loop(agent, "request") == "done"
    assert len(chat_calls) == 4

    dumped = json.dumps(chat_calls[3], default=str)
    assert dumped.count(payload) == 2


def test_passing_tests_after_edit_stops_without_plan_reminder():
    step = PlanStep(id=1, description="Rewrite tests")
    plan = AgentPlan(goal="Replace merge", steps=[step])
    write_call = SimpleNamespace(
        id="write-1",
        function=SimpleNamespace(
            name="write_file",
            arguments='{"path": "a.py", "content": "print(1)"}',
        ),
    )
    test_call = SimpleNamespace(
        id="test-1",
        function=SimpleNamespace(
            name="run_tests",
            arguments="{}",
        ),
    )
    chat_calls = []
    responses = iter(
        [
            _LoopResponse([write_call]),
            _LoopResponse([test_call]),
            _LoopResponse([], "should not be requested"),
        ]
    )

    def chat(**kwargs):
        chat_calls.append(kwargs["messages"])
        return next(responses)

    def execute(name, arguments):
        if name == "write_file":
            return "Successfully wrote file: a.py"
        return "Exit code: 0\nSTDOUT:\n39 passed in 0.13s\n"

    agent = SimpleNamespace(
        max_steps=5,
        max_step_attempts=5,
        active_plan=plan,
        llm=SimpleNamespace(chat=chat),
        registry=SimpleNamespace(
            get_schemas=lambda: [],
            execute=execute,
        ),
        progress=ProgressController(),
        recovery=RecoveryController(),
        replan=lambda reason: "Plan successfully revised.",
        _build_system_prompt=lambda **kwargs: "system",
        _step_likely_requires_edit=lambda step: False,
    )

    result = run_agent_loop(agent, "request")

    assert len(chat_calls) == 2
    assert "Task validated" in result
    assert "tests passed" in result.lower()
    assert "plan is not finished" not in json.dumps(
        chat_calls,
        default=str,
    )


def test_system_prompt_is_stable_and_turn_context_has_budget():
    from minicodex.agent.agent import MiniCodexAgent

    agent = MiniCodexAgent(
        llm=SimpleNamespace(),
        registry=SimpleNamespace(),
    )
    step = PlanStep(id=1, description="Do work")
    plan = AgentPlan(goal="Ship it", steps=[step])

    system = agent._build_system_prompt(
        user_input="goal text UNIQUE123",
        plan=plan,
        current_step=step,
        remaining_agent_steps=7,
    )
    turn = agent._build_turn_context(
        plan=plan,
        current_step=step,
        remaining_agent_steps=7,
    )

    assert "Remaining agent steps" not in system
    assert "UNIQUE123" not in system
    assert "Do not keep working just to mark plan steps complete" in system
    assert "Remaining agent steps: 7" in turn
    assert "Do work" in turn


def test_read_file_defaults_to_200_line_window(tmp_path):
    target = tmp_path / "big.py"
    target.write_text(
        "\n".join(f"line-{i}" for i in range(1, 251)),
        encoding="utf-8",
    )

    result = ReadFileTool(tmp_path).execute("big.py")

    assert "lines 1-200 of 250" in result
    assert "Use offset=201 to continue." in result
    assert "line-1" in result
    assert "line-200" in result
    assert "line-201" not in result

    rest = ReadFileTool(tmp_path).execute("big.py", offset=201)

    assert "lines 201-250 of 250" in rest
    assert "line-250" in rest


def test_partial_validation_does_not_finish_entire_task():
    step = PlanStep(id=1, description="Implement feature")
    plan = AgentPlan(goal="Ship feature", steps=[step])
    write_call = SimpleNamespace(
        id="write-1",
        function=SimpleNamespace(
            name="write_file",
            arguments='{"path": "a.py", "content": "done"}',
        ),
    )
    test_call = SimpleNamespace(
        id="test-1",
        function=SimpleNamespace(
            name="run_tests",
            arguments='{"path": "tests/test_unrelated.py"}',
        ),
    )
    chat_calls = []
    responses = iter(
        [
            _LoopResponse([write_call]),
            _LoopResponse([test_call]),
            _LoopResponse([], "model stopped"),
        ]
    )

    def chat(**kwargs):
        chat_calls.append(kwargs["messages"])
        return next(responses)

    agent = SimpleNamespace(
        max_steps=3,
        max_step_attempts=5,
        active_plan=plan,
        llm=SimpleNamespace(chat=chat),
        registry=SimpleNamespace(
            get_schemas=lambda: [],
            execute=lambda name, arguments: (
                "Successfully wrote file: a.py"
                if name == "write_file"
                else "Exit code: 0\nSUMMARY:\n1 passed"
            ),
        ),
        progress=ProgressController(),
        recovery=RecoveryController(),
        replan=lambda reason: "Plan successfully revised.",
        _build_system_prompt=lambda **kwargs: "system",
        _step_likely_requires_edit=lambda current_step: False,
    )

    result = run_agent_loop(agent, "request")

    assert len(chat_calls) == 3
    assert "Task validated" not in result
    assert not agent.progress.has_validated_edit


def test_recovery_adds_results_for_skipped_tool_calls():
    test_call = SimpleNamespace(
        id="test-1",
        function=SimpleNamespace(
            name="run_tests",
            arguments="{}",
        ),
    )
    skipped_call = SimpleNamespace(
        id="write-1",
        function=SimpleNamespace(
            name="write_file",
            arguments='{"path": "a.py", "content": "x"}',
        ),
    )
    progress = ProgressController(max_validation_no_progress=2)
    progress.last_validation_failed_count = 2
    progress.validation_no_progress_count = 1
    chat_calls = []
    responses = iter(
        [
            _LoopResponse([test_call, skipped_call]),
            _LoopResponse([], "done"),
        ]
    )

    def chat(**kwargs):
        chat_calls.append(kwargs["messages"])
        return next(responses)

    agent = SimpleNamespace(
        max_steps=2,
        max_step_attempts=5,
        active_plan=None,
        llm=SimpleNamespace(chat=chat),
        registry=SimpleNamespace(
            get_schemas=lambda: [],
            execute=lambda name, arguments: (
                "Exit code: 1\nSUMMARY:\n2 failed"
            ),
        ),
        progress=progress,
        recovery=RecoveryController(),
        replan=lambda reason: "Plan successfully revised.",
        _build_system_prompt=lambda **kwargs: "system",
        _step_likely_requires_edit=lambda current_step: False,
    )

    assert run_agent_loop(agent, "request") == "done"
    tool_messages = [
        message
        for message in chat_calls[1]
        if message.get("role") == "tool"
    ]
    assert {message["tool_call_id"] for message in tool_messages} == {
        "test-1",
        "write-1",
    }
    assert "skipped" in tool_messages[-1]["content"].lower()


def test_new_edit_invalidates_previous_full_validation():
    progress = ProgressController()

    progress.record_successful_edit()
    progress.mark_edit_validated()
    assert progress.has_validated_edit

    progress.record_successful_edit()
    assert not progress.has_validated_edit


def test_context_summary_does_not_report_failed_patch_as_ok():
    summary = summarize_tool_result(
        "patch_file",
        '{"path": "a.py"}',
        "Tool execution failed: ValueError: old_text missing",
    )

    assert summary == "[patch_file] a.py FAILED"


def test_search_code_limits_results_and_reports_truncation(tmp_path):
    (tmp_path / "a.py").write_text(
        "\n".join(["needle"] * 5),
        encoding="utf-8",
    )

    result = SearchCodeTool(tmp_path).execute(
        "needle",
        max_results=2,
    )

    assert result.count("a.py:") == 2
    assert "Results truncated at 2 matches" in result


def test_pytest_output_keeps_summary_and_failure_details():
    stdout = (
        "." * 80
        + "\n"
        "=================================== FAILURES ===================================\n"
        "E         AssertionError\n"
        "FAILED tests/test_foo.py::test_bar\n"
        "1 failed, 38 passed in 0.13s\n"
    )

    result = compact_pytest_output(1, stdout, "")

    assert "Exit code: 1" in result
    assert "1 failed, 38 passed" in result
    assert "FAILED tests/test_foo.py::test_bar" in result
    assert "AssertionError" in result
    assert "." * 80 not in result
