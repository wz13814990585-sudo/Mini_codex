import asyncio
import time
from types import (
    SimpleNamespace,
)

import pytest

from ..agent.runtime import (
    AsyncAgentRunner,
    AsyncTaskStatus,
)
from ..agent.runtime import (
    CancellationToken,
    ExecutionCancelled,
)
from ..agent.observability import (
    TraceEventType,
    TraceRecorder,
)


# =============================================================
# Cancellation Token
# =============================================================


def test_cancellation_token():

    token = (
        CancellationToken()
    )

    assert (
        token.is_cancelled
        is False
    )

    assert (
        token.cancel(
            "stop"
        )
        is True
    )

    assert (
        token.is_cancelled
        is True
    )

    assert (
        token.reason
        == "stop"
    )

    assert (
        token.cancel(
            "again"
        )
        is False
    )

    with pytest.raises(
        ExecutionCancelled,
        match="stop",
    ):

        token.raise_if_cancelled()


# =============================================================
# Fake Agent
# =============================================================


class FakeAgent:

    def __init__(
        self,
        *,
        delay=0.0,
    ):

        self.delay = (
            delay
        )

        self.llm = (
            SimpleNamespace()
        )

        self.tool_executor = (
            SimpleNamespace()
        )

        self.planner = None

        self.replanner = None

        self.trace_recorder = (
            TraceRecorder()
        )

    def run(
        self,
        user_input,
        use_planning=True,
    ):

        self.trace_recorder.start_task(
            prompt=(
                user_input
            )
        )

        self.trace_recorder.emit(
            TraceEventType.LLM_STARTED,
            {}
        )

        if (
            self.delay
            > 0
        ):

            time.sleep(
                self.delay
            )

        self.trace_recorder.emit(
            TraceEventType.LLM_FINISHED,
            {}
        )

        return (
            f"Done: {user_input}"
        )


# =============================================================
# Completed Async Task
# =============================================================


@pytest.mark.asyncio
async def test_async_agent_task_completes():

    agent = (
        FakeAgent()
    )

    runner = (
        AsyncAgentRunner(
            agent=(
                agent
            )
        )
    )

    result = (
        await runner.run(
            "hello",
            use_planning=False,
        )
    )

    assert (
        result.status
        == (
            AsyncTaskStatus
            .COMPLETED
        )
    )

    assert (
        result.output
        == "Done: hello"
    )

    assert (
        result.cancelled
        is False
    )


# =============================================================
# Streaming
# =============================================================


@pytest.mark.asyncio
async def test_async_task_streams_trace_events():

    agent = (
        FakeAgent(
            delay=0.05
        )
    )

    runner = (
        AsyncAgentRunner(
            agent=(
                agent
            ),
            poll_interval=0.01,
        )
    )

    task = (
        runner.start(
            "stream me",
            use_planning=False,
        )
    )

    events = []

    async for event in (
        task.stream()
    ):

        events.append(
            event
        )

    event_types = [
        event.event_type
        for event
        in events
    ]

    assert (
        "task_started"
        in event_types
    )

    assert (
        "llm_started"
        in event_types
    )

    assert (
        "llm_finished"
        in event_types
    )

    assert (
        event_types[
            -1
        ]
        == "async_task_finished"
    )

    assert (
        events[
            -1
        ].terminal
        is True
    )


# =============================================================
# Only One Task Per Agent
# =============================================================


def test_same_agent_cannot_run_two_tasks_concurrently():

    agent = (
        FakeAgent(
            delay=0.2
        )
    )

    runner = (
        AsyncAgentRunner(
            agent=(
                agent
            )
        )
    )

    first = (
        runner.start(
            "first",
            use_planning=False,
        )
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "already has a running task"
        ),
    ):

        runner.start(
            "second",
            use_planning=False,
        )

    # Avoid leaking the daemon task through the rest of tests.
    while not (
        first.done
    ):

        time.sleep(
            0.01
        )


# =============================================================
# Cooperative Cancel
# =============================================================


class SlowBoundaryLLM:

    def chat(
        self,
        *args,
        **kwargs,
    ):

        time.sleep(
            0.1
        )

        return (
            SimpleNamespace(
                message=(
                    SimpleNamespace(
                        content="done",
                        tool_calls=[],
                    )
                ),
                usage=(
                    SimpleNamespace(
                        prompt_tokens=1,
                        completion_tokens=1,
                        total_tokens=2,
                    )
                ),
            )
        )


class LLMUsingAgent:

    def __init__(
        self,
    ):

        self.llm = (
            SlowBoundaryLLM()
        )

        self.tool_executor = (
            SimpleNamespace()
        )

        self.planner = None

        self.replanner = None

        self.trace_recorder = (
            TraceRecorder()
        )

    def run(
        self,
        user_input,
        use_planning=True,
    ):

        self.llm.chat(
            messages=[],
            tools=[],
        )

        return (
            "should not complete"
        )


@pytest.mark.asyncio
async def test_cancel_is_observed_after_inflight_llm_boundary():

    agent = (
        LLMUsingAgent()
    )

    runner = (
        AsyncAgentRunner(
            agent=(
                agent
            )
        )
    )

    task = (
        runner.start(
            "slow",
            use_planning=False,
        )
    )

    await asyncio.sleep(
        0.02
    )

    assert (
        task.cancel(
            "user cancelled"
        )
        is True
    )

    result = (
        await task.result()
    )

    assert (
        result.status
        == (
            AsyncTaskStatus
            .CANCELLED
        )
    )

    assert (
        result.cancelled
        is True
    )

    assert (
        "user cancelled"
        in (
            result.error
            or ""
        )
    )


# =============================================================
# Runtime Is Restored
# =============================================================


@pytest.mark.asyncio
async def test_runtime_wrappers_are_restored_after_task():

    agent = (
        FakeAgent()
    )

    original_llm = (
        agent.llm
    )

    original_executor = (
        agent.tool_executor
    )

    runner = (
        AsyncAgentRunner(
            agent=(
                agent
            )
        )
    )

    result = (
        await runner.run(
            "hello",
            use_planning=False,
        )
    )

    assert (
        result.status
        == (
            AsyncTaskStatus
            .COMPLETED
        )
    )

    assert (
        agent.llm
        is original_llm
    )

    assert (
        agent.tool_executor
        is original_executor
    )


# =============================================================
# Failed Agent
# =============================================================


class BrokenAgent(
    FakeAgent
):

    def run(
        self,
        user_input,
        use_planning=True,
    ):

        raise RuntimeError(
            "boom"
        )


@pytest.mark.asyncio
async def test_async_failure_is_structured():

    runner = (
        AsyncAgentRunner(
            agent=(
                BrokenAgent()
            )
        )
    )

    result = (
        await runner.run(
            "fail",
            use_planning=False,
        )
    )

    assert (
        result.status
        == (
            AsyncTaskStatus
            .FAILED
        )
    )

    assert (
        "boom"
        in (
            result.error
            or ""
        )
    )