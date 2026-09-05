from ..agent.working_summary import WorkingSummary
from ..tools.results import ToolResult


def test_working_summary_initial_state():

    summary = WorkingSummary()

    assert summary.items == []

    assert (
        summary.render()
        == (
            "No important execution facts "
            "have been recorded yet."
        )
    )


def test_working_summary_adds_unique_facts():

    summary = WorkingSummary()

    summary.add(
        "Inspected file: app.py."
    )

    summary.add(
        "Inspected file: app.py."
    )

    assert summary.items == [
        "Inspected file: app.py."
    ]


def test_working_summary_respects_max_items():

    summary = WorkingSummary(
        max_items=3
    )

    summary.add("Fact 1")
    summary.add("Fact 2")
    summary.add("Fact 3")
    summary.add("Fact 4")

    assert summary.items == [
        "Fact 2",
        "Fact 3",
        "Fact 4",
    ]


def test_working_summary_reset():

    summary = WorkingSummary()

    summary.add(
        "Some fact"
    )

    assert summary.items

    summary.reset()

    assert summary.items == []


def test_record_read_file_success():

    summary = WorkingSummary()

    result = ToolResult(
        success=True,
        summary="File read.",
        data={},
        error=None,
    )

    summary.record_tool_result(
        tool_name="read_file",
        arguments={
            "path": "app.py"
        },
        result=result,
    )

    assert (
        "Inspected file: app.py."
        in summary.items
    )


def test_record_read_file_failure():

    summary = WorkingSummary()

    result = ToolResult(
        success=False,
        summary="Read failed.",
        data={},
        error="File not found",
    )

    summary.record_tool_result(
        tool_name="read_file",
        arguments={
            "path": "missing.py"
        },
        result=result,
    )

    assert any(
        (
            "read_file"
            in item
            and "missing.py"
            in item
            and "File not found"
            in item
        )
        for item
        in summary.items
    )


def test_record_patch_file_success():

    summary = WorkingSummary()

    result = ToolResult(
        success=True,
        summary="Patched.",
        data={},
        error=None,
    )

    summary.record_tool_result(
        tool_name="patch_file",
        arguments={
            "path": "app.py"
        },
        result=result,
    )

    assert (
        "Modified file successfully: app.py."
        in summary.items
    )


def test_record_write_file_success():

    summary = WorkingSummary()

    result = ToolResult(
        success=True,
        summary="Written.",
        data={},
        error=None,
    )

    summary.record_tool_result(
        tool_name="write_file",
        arguments={
            "path": "new.py"
        },
        result=result,
    )

    assert (
        "Modified file successfully: new.py."
        in summary.items
    )


def test_record_run_tests_passed():

    summary = WorkingSummary()

    result = ToolResult(
        success=True,
        summary="Tests ran.",
        data={
            "tests_passed": True,
            "passed": 12,
            "failed": 0,
            "errors": 0,
        },
        error=None,
    )

    summary.record_tool_result(
        tool_name="run_tests",
        arguments={
            "path": "."
        },
        result=result,
    )

    assert (
        "Validation passed: "
        "12 tests passed, "
        "0 failures."
        in summary.items
    )


def test_record_run_tests_failed():

    summary = WorkingSummary()

    result = ToolResult(
        success=True,
        summary="Tests ran.",
        data={
            "tests_passed": False,
            "passed": 8,
            "failed": 2,
            "errors": 1,
        },
        error=None,
    )

    summary.record_tool_result(
        tool_name="run_tests",
        arguments={
            "path": "."
        },
        result=result,
    )

    assert (
        "Validation still failing: "
        "8 passed, "
        "2 failed, "
        "1 errors."
        in summary.items
    )


def test_record_command_success():

    summary = WorkingSummary()

    result = ToolResult(
        success=True,
        summary="Command ran.",
        data={
            "command_succeeded": True
        },
        error=None,
    )

    summary.record_tool_result(
        tool_name="run_command",
        arguments={
            "command": "python app.py"
        },
        result=result,
    )

    assert (
        "Command succeeded: "
        "python app.py."
        in summary.items
    )


def test_record_complete_plan_step():

    summary = WorkingSummary()

    result = ToolResult(
        success=True,
        summary="Step completed.",
        data={
            "completed": True,
            "step_id": 2,
            "step_description": (
                "Fix parser"
            ),
        },
        error=None,
    )

    summary.record_tool_result(
        tool_name=(
            "complete_plan_step"
        ),
        arguments={},
        result=result,
    )

    assert (
        "Completed plan step "
        "2: Fix parser."
        in summary.items
    )


def test_record_replan():

    summary = WorkingSummary()

    result = ToolResult(
        success=True,
        summary="Replanned.",
        data={
            "replanned": True,
            "reason": (
                "Original assumption was wrong"
            ),
        },
        error=None,
    )

    summary.record_tool_result(
        tool_name="replan",
        arguments={},
        result=result,
    )

    assert (
        "Implementation plan was revised. "
        "Reason: Original assumption was wrong"
        in summary.items
    )


def test_render_formats_summary():

    summary = WorkingSummary()

    summary.add(
        "Inspected file: app.py."
    )

    summary.add(
        "Modified file successfully: app.py."
    )

    rendered = (
        summary.render()
    )

    assert (
        "- Inspected file: app.py."
        in rendered
    )

    assert (
        "- Modified file successfully: app.py."
        in rendered
    )

from types import SimpleNamespace

from ..agent.agent import MiniCodexAgent
from ..llm.types import (
    LLMResponse,
    TokenUsage,
)
from ..tools.results import ToolResult


class FakeToolCall:

    def __init__(
        self,
        call_id,
        name,
        arguments,
    ):
        self.id = call_id

        self.type = "function"

        self.function = (
            SimpleNamespace(
                name=name,
                arguments=arguments,
            )
        )


class FakeMessage:

    def __init__(
        self,
        *,
        content=None,
        tool_calls=None,
    ):
        self.content = content

        self.tool_calls = (
            tool_calls
            if tool_calls is not None
            else []
        )

    def model_dump(
        self,
        exclude_none=True,
    ):

        payload = {
            "role": "assistant",
        }

        if self.content is not None:

            payload["content"] = (
                self.content
            )

        if self.tool_calls:

            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": (
                            call.function.name
                        ),
                        "arguments": (
                            call.function.arguments
                        ),
                    },
                }
                for call
                in self.tool_calls
            ]

        return payload


class FakeLLM:

    def __init__(
        self,
    ):
        self.call_count = 0

    def chat(
        self,
        messages,
        tools=None,
    ):

        self.call_count += 1

        # First round:
        # ask Agent to read app.py
        if self.call_count == 1:

            return LLMResponse(
                message=FakeMessage(
                    tool_calls=[
                        FakeToolCall(
                            call_id="call-1",
                            name="read_file",
                            arguments=(
                                '{"path": "app.py"}'
                            ),
                        )
                    ]
                ),
                usage=TokenUsage(
                    prompt_tokens=100,
                    completion_tokens=20,
                    total_tokens=120,
                ),
            )

        # Second round:
        # finish normally.
        if self.call_count == 2:

            return LLMResponse(
                message=FakeMessage(
                    content="Done.",
                    tool_calls=[],
                ),
                usage=TokenUsage(
                    prompt_tokens=150,
                    completion_tokens=20,
                    total_tokens=170,
                ),
            )

        raise AssertionError(
            "Unexpected extra LLM call."
        )


class FakeRegistry:

    def get_schemas(
        self,
    ):
        return []

    def execute(
        self,
        tool_name,
        arguments,
    ):

        assert (
            tool_name
            == "read_file"
        )

        assert (
            arguments["path"]
            == "app.py"
        )

        return ToolResult(
            success=True,
            summary="File read successfully.",
            data={
                "path": "app.py",
            },
            error=None,
        )


def test_loop_records_tool_fact_in_working_summary():

    agent = MiniCodexAgent(
        llm=FakeLLM(),
        registry=FakeRegistry(),
        planner=None,
        replanner=None,
        max_steps=3,
        max_context_tokens=1000,
    )

    result = agent.run(
        "Inspect app.py",
        use_planning=False,
    )

    assert result == "Done."

    assert (
        "Inspected file: app.py."
        in agent.working_summary.items
    )

def test_working_summary_is_visible_to_next_llm_turn():

    class InspectingLLM:

        def __init__(
            self,
        ):
            self.call_count = 0

        def chat(
            self,
            messages,
            tools=None,
        ):

            self.call_count += 1

            if self.call_count == 1:

                return LLMResponse(
                    message=FakeMessage(
                        tool_calls=[
                            FakeToolCall(
                                call_id="call-1",
                                name="read_file",
                                arguments=(
                                    '{"path": "app.py"}'
                                ),
                            )
                        ]
                    ),
                    usage=TokenUsage(
                        prompt_tokens=100,
                        completion_tokens=20,
                        total_tokens=120,
                    ),
                )

            if self.call_count == 2:

                combined_text = "\n".join(
                    str(
                        message.get(
                            "content",
                            "",
                        )
                    )
                    for message
                    in messages
                )

                assert (
                    "Inspected file: app.py."
                    in combined_text
                )

                return LLMResponse(
                    message=FakeMessage(
                        content="Done.",
                        tool_calls=[],
                    ),
                    usage=TokenUsage(
                        prompt_tokens=200,
                        completion_tokens=20,
                        total_tokens=220,
                    ),
                )

            raise AssertionError(
                "Unexpected extra LLM call."
            )

    agent = MiniCodexAgent(
        llm=InspectingLLM(),
        registry=FakeRegistry(),
        planner=None,
        replanner=None,
        max_steps=3,
    )

    result = agent.run(
        "Inspect app.py",
        use_planning=False,
    )

    assert result == "Done."

def test_working_summary_resets_between_tasks():

    class FinalOnlyLLM:

        def chat(
            self,
            messages,
            tools=None,
        ):

            return LLMResponse(
                message=FakeMessage(
                    content="Done.",
                    tool_calls=[],
                ),
                usage=TokenUsage(
                    prompt_tokens=50,
                    completion_tokens=10,
                    total_tokens=60,
                ),
            )

    agent = MiniCodexAgent(
        llm=FinalOnlyLLM(),
        registry=FakeRegistry(),
        planner=None,
        replanner=None,
    )

    agent.working_summary.add(
        "Old task fact."
    )

    assert (
        "Old task fact."
        in agent.working_summary.items
    )

    agent.run(
        "New task",
        use_planning=False,
    )

    assert (
        "Old task fact."
        not in agent.working_summary.items
    )