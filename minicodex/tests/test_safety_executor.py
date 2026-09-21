from ..agent.safety import (
    SafetyLevel,
    SafetyDecision,
)
from ..agent.safety import (
    SafetyToolExecutor,
)
from ..agent.runtime import (
    PreparedToolCall,
    ToolExecution,
)

from ..tools.results import (
    ToolResult,
)


# =============================================================
# Fake Downstream Executor
# =============================================================


class FakeExecutor:

    def __init__(
        self,
    ):

        self.execution_count = 0

    def prepare(
        self,
        tool_name: str,
        raw_arguments: str,
    ):

        raise NotImplementedError

    def execute_prepared(
        self,
        prepared,
    ):

        self.execution_count += 1

        return ToolExecution(
            tool_name=(
                prepared.tool_name
            ),
            arguments=(
                prepared.arguments
            ),
            result=ToolResult(
                success=True,
                summary=(
                    "Downstream executed."
                ),
                data={},
            ),
        )


# =============================================================
# Fake Policy
# =============================================================


class FakePolicy:

    def __init__(
        self,
        decision,
    ):

        self.decision = (
            decision
        )

    def assess(
        self,
        tool_name,
        arguments,
    ):

        return (
            self.decision
        )


# =============================================================
# Blocked Never Reaches Tool
# =============================================================


def test_blocked_call_never_reaches_downstream_executor():

    downstream = (
        FakeExecutor()
    )

    decision = (
        SafetyDecision(
            level=(
                SafetyLevel.BLOCKED
            ),
            allowed=False,
            reason=(
                "Blocked for test."
            ),
            rule=(
                "test_block"
            ),
            tool_name=(
                "run_command"
            ),
            command=(
                "danger"
            ),
        )
    )

    executor = (
        SafetyToolExecutor(
            executor=(
                downstream
            ),
            policy=(
                FakePolicy(
                    decision
                )
            ),
        )
    )

    prepared = (
        PreparedToolCall(
            tool_name=(
                "run_command"
            ),
            arguments={
                "command": (
                    "danger"
                ),
            },
        )
    )

    execution = (
        executor
        .execute_prepared(
            prepared
        )
    )

    assert (
        execution.result.success
        is False
    )

    assert (
        execution.result.data[
            "failure_type"
        ]
        == "safety_blocked"
    )

    assert (
        downstream.execution_count
        == 0
    )


# =============================================================
# Safe Reaches Tool
# =============================================================


def test_safe_call_reaches_downstream_executor():

    downstream = (
        FakeExecutor()
    )

    decision = (
        SafetyDecision(
            level=(
                SafetyLevel.SAFE
            ),
            allowed=True,
            reason=(
                "Safe for test."
            ),
            rule=(
                "test_safe"
            ),
            tool_name=(
                "read_file"
            ),
        )
    )

    executor = (
        SafetyToolExecutor(
            executor=(
                downstream
            ),
            policy=(
                FakePolicy(
                    decision
                )
            ),
        )
    )

    prepared = (
        PreparedToolCall(
            tool_name=(
                "read_file"
            ),
            arguments={
                "path": (
                    "demo.py"
                ),
            },
        )
    )

    execution = (
        executor
        .execute_prepared(
            prepared
        )
    )

    assert (
        execution.result.success
        is True
    )

    assert (
        downstream.execution_count
        == 1
    )

    assert (
        execution.result.data[
            "safety"
        ][
            "level"
        ]
        == "safe"
    )


# =============================================================
# Caution Executes But Carries Warning
# =============================================================


def test_caution_call_executes_with_warning():

    downstream = (
        FakeExecutor()
    )

    decision = (
        SafetyDecision(
            level=(
                SafetyLevel.CAUTION
            ),
            allowed=True,
            reason=(
                "Touches pre-existing user work."
            ),
            rule=(
                "preexisting_user_change"
            ),
            tool_name=(
                "write_file"
            ),
            path=(
                "demo.py"
            ),
        )
    )

    executor = (
        SafetyToolExecutor(
            executor=(
                downstream
            ),
            policy=(
                FakePolicy(
                    decision
                )
            ),
        )
    )

    prepared = (
        PreparedToolCall(
            tool_name=(
                "write_file"
            ),
            arguments={
                "path": (
                    "demo.py"
                ),
                "content": (
                    "hello"
                ),
            },
        )
    )

    execution = (
        executor
        .execute_prepared(
            prepared
        )
    )

    assert (
        execution.result.success
        is True
    )

    assert (
        downstream.execution_count
        == 1
    )

    assert (
        execution.result.data[
            "safety"
        ][
            "level"
        ]
        == "caution"
    )

    assert (
        "safety_warning"
        in execution.result.data
    )


# =============================================================
# Policy Failure Fails Closed
# =============================================================


def test_policy_exception_fails_closed():

    class BrokenPolicy:

        def assess(
            self,
            tool_name,
            arguments,
        ):

            raise RuntimeError(
                "policy crashed"
            )

    downstream = (
        FakeExecutor()
    )

    executor = (
        SafetyToolExecutor(
            executor=(
                downstream
            ),
            policy=(
                BrokenPolicy()
            ),
        )
    )

    prepared = (
        PreparedToolCall(
            tool_name=(
                "run_command"
            ),
            arguments={
                "command": (
                    "python demo.py"
                ),
            },
        )
    )

    execution = (
        executor
        .execute_prepared(
            prepared
        )
    )

    assert (
        execution.result.success
        is False
    )

    assert (
        execution.result.data[
            "failure_type"
        ]
        == "safety_policy_failure"
    )

    # Most important invariant:
    assert (
        downstream.execution_count
        == 0
    )