from ..agent.tool_executor import (
    PreparedToolCall,
    ToolExecution,
    ToolExecutor,
)
from ..tools.results import ToolResult


class FakeRegistry:

    def __init__(
        self,
        result=None,
        error=None,
    ):
        self.result = result
        self.error = error

    def execute(
        self,
        name: str,
        arguments: dict,
    ):
        if self.error is not None:
            raise self.error

        return self.result


def test_prepare_parses_arguments():

    executor = ToolExecutor(
        FakeRegistry()
    )

    prepared = executor.prepare(
        tool_name="read_file",
        raw_arguments=(
            '{"path": "main.py"}'
        ),
    )

    assert isinstance(
        prepared,
        PreparedToolCall,
    )

    assert prepared.error is None

    assert prepared.arguments == {
        "path": "main.py"
    }


def test_prepare_handles_invalid_json():

    executor = ToolExecutor(
        FakeRegistry()
    )

    prepared = executor.prepare(
        tool_name="read_file",
        raw_arguments=(
            '{"path": "main.py"'
        ),
    )

    assert prepared.error is not None
    assert prepared.error.success is False

    assert (
        prepared.error.data[
            "failure_type"
        ]
        == "argument_parsing"
    )


def test_prepare_rejects_non_object_json():

    executor = ToolExecutor(
        FakeRegistry()
    )

    prepared = executor.prepare(
        tool_name="read_file",
        raw_arguments='["main.py"]',
    )

    assert prepared.error is not None

    assert (
        prepared.error.data[
            "failure_type"
        ]
        == "invalid_argument_shape"
    )


def test_execute_returns_valid_tool_result():

    expected = ToolResult(
        success=True,
        summary="Tool succeeded.",
    )

    executor = ToolExecutor(
        FakeRegistry(
            result=expected
        )
    )

    prepared = executor.prepare(
        tool_name="fake_tool",
        raw_arguments="{}",
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    assert isinstance(
        execution,
        ToolExecution,
    )

    assert execution.result is expected
    assert execution.result.success is True


def test_execute_normalizes_exception():

    executor = ToolExecutor(
        FakeRegistry(
            error=ValueError(
                "Something went wrong."
            )
        )
    )

    prepared = executor.prepare(
        tool_name="fake_tool",
        raw_arguments="{}",
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    assert execution.result.success is False

    assert (
        execution.result.data[
            "failure_type"
        ]
        == "execution"
    )

    assert (
        "ValueError"
        in execution.result.error
    )


def test_execute_rejects_invalid_result_type():

    executor = ToolExecutor(
        FakeRegistry(
            result="legacy string result"
        )
    )

    prepared = executor.prepare(
        tool_name="bad_tool",
        raw_arguments="{}",
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    assert execution.result.success is False

    assert (
        execution.result.data[
            "failure_type"
        ]
        == "invalid_result_type"
    )

    assert (
        execution.result.data[
            "returned_type"
        ]
        == "str"
    )


def test_execute_prepared_is_safe_after_prepare_failure():

    executor = ToolExecutor(
        FakeRegistry()
    )

    prepared = executor.prepare(
        tool_name="fake_tool",
        raw_arguments="{broken",
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    assert execution.result.success is False

    assert (
        execution.result.data[
            "failure_type"
        ]
        == "argument_parsing"
    )