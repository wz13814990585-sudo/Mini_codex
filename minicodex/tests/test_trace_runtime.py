from dataclasses import dataclass

from ..agent.trace import (
    TraceEventType,
    TraceRecorder,
)
from ..agent.trace_runtime import (
    TracingLLMClient,
    TracingRollbackEngine,
    TracingToolExecutor,
)

from ..agent.tool_executor import (
    PreparedToolCall,
    ToolExecution,
)

from ..llm.types import (
    LLMResponse,
    TokenUsage,
)

from ..tools.results import (
    ToolResult,
)


# =============================================================
# Fake Message
# =============================================================


@dataclass
class FakeMessage:

    content: str = "done"

    tool_calls: list | None = None


# =============================================================
# Fake LLM
# =============================================================


class FakeLLM:

    def chat(
        self,
        *args,
        **kwargs,
    ):

        return LLMResponse(
            message=(
                FakeMessage(
                    content="done",
                    tool_calls=[],
                )
            ),
            usage=(
                TokenUsage(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                )
            ),
        )


# =============================================================
# LLM Trace
# =============================================================


def test_llm_trace():

    recorder = (
        TraceRecorder()
    )

    recorder.start_task(
        prompt="test"
    )

    llm = (
        TracingLLMClient(
            client=(
                FakeLLM()
            ),
            recorder=(
                recorder
            ),
        )
    )

    response = (
        llm.chat(
            messages=[
                {
                    "role": "user",
                    "content": "hello",
                }
            ],
            tools=[],
        )
    )

    assert (
        response.usage.total_tokens
        == 15
    )

    event_types = [
        event.event_type
        for event
        in recorder.events
    ]

    assert (
        TraceEventType.LLM_STARTED
        in event_types
    )

    assert (
        TraceEventType.LLM_FINISHED
        in event_types
    )

    finished = [
        event
        for event
        in recorder.events
        if (
            event.event_type
            == (
                TraceEventType
                .LLM_FINISHED
            )
        )
    ][
        0
    ]

    assert (
        finished.data[
            "total_tokens"
        ]
        == 15
    )


# =============================================================
# Fake Executor
# =============================================================


class FakeExecutor:

    def prepare(
        self,
        tool_name,
        raw_arguments,
    ):

        raise NotImplementedError

    def execute_prepared(
        self,
        prepared,
    ):

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
                    "Edit succeeded."
                ),
                data={
                    "checkpoint_id": (
                        "cp-1"
                    ),
                    "checkpoint_revision": (
                        1
                    ),
                    "checkpoint_sealed": (
                        True
                    ),
                    "safety": {
                        "level": (
                            "safe"
                        ),
                        "allowed": (
                            True
                        ),
                        "rule": (
                            "workspace_edit"
                        ),
                    },
                },
            ),
        )


def test_tool_trace_records_safety_and_edit():

    recorder = (
        TraceRecorder()
    )

    recorder.start_task(
        prompt="edit"
    )

    executor = (
        TracingToolExecutor(
            executor=(
                FakeExecutor()
            ),
            recorder=(
                recorder
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
                    "x = 1"
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

    event_types = [
        event.event_type
        for event
        in recorder.events
    ]

    assert (
        TraceEventType.TOOL_REQUESTED
        in event_types
    )

    assert (
        TraceEventType.SAFETY_DECISION
        in event_types
    )

    assert (
        TraceEventType.TOOL_FINISHED
        in event_types
    )

    assert (
        TraceEventType.EDIT_APPLIED
        in event_types
    )


# =============================================================
# Validation Trace
# =============================================================


class FakeValidationExecutor:

    def execute_prepared(
        self,
        prepared,
    ):

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
                    "Tests completed."
                ),
                data={
                    "passed": 10,
                    "failed": 0,
                    "errors": 0,
                    "skipped": 1,
                },
            ),
        )


def test_validation_trace():

    recorder = (
        TraceRecorder()
    )

    recorder.start_task(
        prompt="validate"
    )

    executor = (
        TracingToolExecutor(
            executor=(
                FakeValidationExecutor()
            ),
            recorder=(
                recorder
            ),
        )
    )

    prepared = (
        PreparedToolCall(
            tool_name=(
                "run_tests"
            ),
            arguments={
                "path": (
                    "."
                ),
                "purpose": (
                    "regression"
                ),
            },
        )
    )

    executor.execute_prepared(
        prepared
    )

    events = [
        event
        for event
        in recorder.events
        if (
            event.event_type
            == (
                TraceEventType
                .VALIDATION_RUN
            )
        )
    ]

    assert (
        len(
            events
        )
        == 1
    )

    assert (
        events[
            0
        ].data[
            "purpose"
        ]
        == "regression"
    )

    assert (
        events[
            0
        ].data[
            "failed"
        ]
        == 0
    )


# =============================================================
# Fake Rollback
# =============================================================


class FakeRollbackEngine:

    def rollback(
        self,
        checkpoint_id,
    ):

        return ToolResult(
            success=True,
            summary=(
                "Rolled back."
            ),
            data={
                "checkpoint_id": (
                    checkpoint_id
                ),
                "path": (
                    "demo.py"
                ),
            },
        )


def test_rollback_trace():

    recorder = (
        TraceRecorder()
    )

    recorder.start_task(
        prompt="rollback"
    )

    engine = (
        TracingRollbackEngine(
            engine=(
                FakeRollbackEngine()
            ),
            recorder=(
                recorder
            ),
        )
    )

    result = (
        engine.rollback(
            "cp-1"
        )
    )

    assert (
        result.success
        is True
    )

    event_types = [
        event.event_type
        for event
        in recorder.events
    ]

    assert (
        TraceEventType.ROLLBACK_STARTED
        in event_types
    )

    assert (
        TraceEventType.ROLLBACK_FINISHED
        in event_types
    )