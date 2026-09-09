"""Async task runtime for MiniCodex."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import asyncio
import threading
import time
import uuid

from .execution_control import (
    CancellationToken,
    ExecutionCancelled,
)


# =============================================================
# Task Status
# =============================================================


class AsyncTaskStatus(
    str,
    Enum,
):

    PENDING = "pending"

    RUNNING = "running"

    CANCELLING = "cancelling"

    CANCELLED = "cancelled"

    COMPLETED = "completed"

    FAILED = "failed"


# =============================================================
# Stream Event
# =============================================================


@dataclass(frozen=True)
class AsyncStreamEvent:

    sequence: int

    event_type: str

    data: dict

    terminal: bool = False

    def to_dict(
        self,
    ) -> dict:

        return {
            "sequence": (
                self.sequence
            ),
            "event_type": (
                self.event_type
            ),
            "data": dict(
                self.data
            ),
            "terminal": (
                self.terminal
            ),
        }


# =============================================================
# Task Result
# =============================================================


@dataclass(frozen=True)
class AsyncTaskResult:

    task_id: str

    status: AsyncTaskStatus

    output: str | None

    error: str | None

    duration_seconds: float

    cancelled: bool


# =============================================================
# Cancellable LLM
# =============================================================


class CancellableLLMClient:
    """
    Add cooperative cancellation checks around one LLM client.

    Important limitation:

        If the underlying synchronous HTTP request is already
        in flight, Python cannot safely kill that thread.

    Cancellation therefore becomes effective immediately after
    that call returns unless the provider itself supports
    transport-level cancellation.
    """

    def __init__(
        self,
        *,
        client,
        token: CancellationToken,
    ):

        self.client = (
            client
        )

        self.token = (
            token
        )

    def chat(
        self,
        *args,
        **kwargs,
    ):

        self.token.raise_if_cancelled()

        response = (
            self.client
            .chat(
                *args,
                **kwargs,
            )
        )

        self.token.raise_if_cancelled()

        return response

    def __getattr__(
        self,
        name,
    ):

        return getattr(
            self.client,
            name,
        )


# =============================================================
# Cancellable Tool Executor
# =============================================================


class CancellableToolExecutor:
    """
    Cooperative cancellation boundary around ToolExecutor.

    Cancellation is checked both before and after the actual
    tool execution.
    """

    def __init__(
        self,
        *,
        executor,
        token: CancellationToken,
    ):

        self.executor = (
            executor
        )

        self.token = (
            token
        )

    def prepare(
        self,
        tool_name: str,
        raw_arguments: str,
    ):

        self.token.raise_if_cancelled()

        return (
            self.executor
            .prepare(
                tool_name=tool_name,
                raw_arguments=(
                    raw_arguments
                ),
            )
        )

    def execute_prepared(
        self,
        prepared,
    ):

        self.token.raise_if_cancelled()

        execution = (
            self.executor
            .execute_prepared(
                prepared
            )
        )

        self.token.raise_if_cancelled()

        return execution

    def __getattr__(
        self,
        name,
    ):

        return getattr(
            self.executor,
            name,
        )


# =============================================================
# Async Agent Task
# =============================================================


class AsyncAgentTask:
    """
    Handle for one background MiniCodex task.

    Consumers can:

        await task.result()

        task.cancel()

        async for event in task.stream():
            ...
    """

    def __init__(
        self,
        *,
        task_id: str,
        agent,
        user_input: str,
        use_planning: bool | None,
        token: CancellationToken,
        policy=None,
        poll_interval: float = 0.05,
    ):

        self.task_id = (
            task_id
        )

        self.agent = (
            agent
        )

        self.user_input = (
            user_input
        )

        self.use_planning = (
            use_planning
        )

        self.policy = policy

        self.token = (
            token
        )

        self.poll_interval = max(
            0.01,
            float(
                poll_interval
            ),
        )

        self._status = (
            AsyncTaskStatus
            .PENDING
        )

        self._status_lock = (
            threading.Lock()
        )

        self._result: (
            AsyncTaskResult
            | None
        ) = None

        self._done = (
            threading.Event()
        )

        self._thread: (
            threading.Thread
            | None
        ) = None

        self._original_llm = None

        self._original_tool_executor = (
            None
        )

    # =========================================================
    # Status
    # =========================================================

    @property
    def status(
        self,
    ) -> AsyncTaskStatus:

        with self._status_lock:

            return (
                self._status
            )

    @property
    def done(
        self,
    ) -> bool:

        return (
            self._done
            .is_set()
        )

    @property
    def cancelled(
        self,
    ) -> bool:

        return (
            self.status
            == (
                AsyncTaskStatus
                .CANCELLED
            )
        )

    def _set_status(
        self,
        status: AsyncTaskStatus,
    ) -> None:

        with self._status_lock:

            self._status = (
                status
            )

    # =========================================================
    # Start
    # =========================================================

    def start(
        self,
    ) -> "AsyncAgentTask":

        if (
            self._thread
            is not None
        ):

            raise RuntimeError(
                (
                    "AsyncAgentTask has "
                    "already been started."
                )
            )

        self._thread = (
            threading.Thread(
                target=(
                    self._worker
                ),
                name=(
                    "MiniCodex-"
                    f"{self.task_id[:8]}"
                ),
                daemon=True,
            )
        )

        self._thread.start()

        return self

    # =========================================================
    # Cancel
    # =========================================================

    def cancel(
        self,
        reason: str = (
            "Task cancelled by caller."
        ),
    ) -> bool:

        if (
            self.done
        ):

            return False

        requested = (
            self.token
            .cancel(
                reason
            )
        )

        if (
            requested
        ):

            self._set_status(
                AsyncTaskStatus
                .CANCELLING
            )

        return (
            requested
        )

    # =========================================================
    # Await Result
    # =========================================================

    async def result(
        self,
    ) -> AsyncTaskResult:

        while not (
            self._done
            .is_set()
        ):

            await asyncio.sleep(
                self.poll_interval
            )

        assert (
            self._result
            is not None
        )

        return (
            self._result
        )

    # =========================================================
    # Stream
    # =========================================================

    async def stream(
        self,
    ):
        """
        Stream structured Trace events while the Agent executes.

        Final lifecycle state is always emitted as the last
        terminal AsyncStreamEvent.

        This reuses Stage 14 Trace instead of inventing a
        second observability format.
        """

        recorder = getattr(
            self.agent,
            "trace_recorder",
            None,
        )

        cursor = 0

        stream_sequence = 0

        while True:

            # =================================================
            # Drain New Trace Events
            # =================================================

            if (
                recorder
                is not None
            ):

                try:

                    snapshot = list(
                        recorder.events
                    )

                except Exception:

                    snapshot = []

                if (
                    cursor
                    < len(
                        snapshot
                    )
                ):

                    for trace_event in (
                        snapshot[
                            cursor:
                        ]
                    ):

                        stream_sequence += 1

                        yield (
                            AsyncStreamEvent(
                                sequence=(
                                    stream_sequence
                                ),
                                event_type=(
                                    trace_event
                                    .event_type
                                    .value
                                ),
                                data=dict(
                                    trace_event
                                    .data
                                ),
                                terminal=False,
                            )
                        )

                    cursor = len(
                        snapshot
                    )

            # =================================================
            # Task Finished
            # =================================================

            if (
                self.done
            ):

                # Final drain in case events arrived between
                # the previous snapshot and completion.
                if (
                    recorder
                    is not None
                ):

                    try:

                        snapshot = list(
                            recorder.events
                        )

                    except Exception:

                        snapshot = []

                    if (
                        cursor
                        < len(
                            snapshot
                        )
                    ):

                        for trace_event in (
                            snapshot[
                                cursor:
                            ]
                        ):

                            stream_sequence += 1

                            yield (
                                AsyncStreamEvent(
                                    sequence=(
                                        stream_sequence
                                    ),
                                    event_type=(
                                        trace_event
                                        .event_type
                                        .value
                                    ),
                                    data=dict(
                                        trace_event
                                        .data
                                    ),
                                    terminal=False,
                                )
                            )

                        cursor = len(
                            snapshot
                        )

                result = (
                    self._result
                )

                stream_sequence += 1

                yield (
                    AsyncStreamEvent(
                        sequence=(
                            stream_sequence
                        ),
                        event_type=(
                            "async_task_finished"
                        ),
                        data={
                            "task_id": (
                                self.task_id
                            ),
                            "status": (
                                (
                                    result.status.value
                                )
                                if result
                                else (
                                    self.status.value
                                )
                            ),
                            "output": (
                                result.output
                                if result
                                else None
                            ),
                            "error": (
                                result.error
                                if result
                                else None
                            ),
                            "cancelled": (
                                result.cancelled
                                if result
                                else False
                            ),
                        },
                        terminal=True,
                    )
                )

                return

            await asyncio.sleep(
                self.poll_interval
            )

    # =========================================================
    # Worker
    # =========================================================

    def _worker(
        self,
    ) -> None:

        started = (
            time.perf_counter()
        )

        self._set_status(
            AsyncTaskStatus
            .RUNNING
        )

        self._install_cancellation_boundaries()

        try:

            self.token.raise_if_cancelled()

            run_kwargs = {"use_planning": self.use_planning}
            if self.policy is not None:
                run_kwargs["policy"] = self.policy
            output = self.agent.run(self.user_input, **run_kwargs)

            self.token.raise_if_cancelled()

        except ExecutionCancelled as e:

            try:
                from ..validation import TaskOutcome
                state = getattr(self.agent, "task_state", None)
                if state is not None:
                    state.finish(TaskOutcome.CANCELLED)
                metrics = getattr(self.agent, "execution_metrics", None)
                if metrics is not None:
                    metrics.finish(TaskOutcome.CANCELLED.value, str(e))
            except Exception:
                pass

            self._set_status(
                AsyncTaskStatus
                .CANCELLED
            )

            self._result = (
                AsyncTaskResult(
                    task_id=(
                        self.task_id
                    ),
                    status=(
                        AsyncTaskStatus
                        .CANCELLED
                    ),
                    output=None,
                    error=str(
                        e
                    ),
                    duration_seconds=(
                        time.perf_counter()
                        - started
                    ),
                    cancelled=True,
                )
            )

        except Exception as e:

            self._set_status(
                AsyncTaskStatus
                .FAILED
            )

            self._result = (
                AsyncTaskResult(
                    task_id=(
                        self.task_id
                    ),
                    status=(
                        AsyncTaskStatus
                        .FAILED
                    ),
                    output=None,
                    error=(
                        f"{type(e).__name__}: "
                        f"{e}"
                    ),
                    duration_seconds=(
                        time.perf_counter()
                        - started
                    ),
                    cancelled=False,
                )
            )

        else:

            self._set_status(
                AsyncTaskStatus
                .COMPLETED
            )

            self._result = (
                AsyncTaskResult(
                    task_id=(
                        self.task_id
                    ),
                    status=(
                        AsyncTaskStatus
                        .COMPLETED
                    ),
                    output=str(
                        output
                    ),
                    error=None,
                    duration_seconds=(
                        time.perf_counter()
                        - started
                    ),
                    cancelled=False,
                )
            )

        finally:

            self._restore_runtime()

            self._done.set()

    # =========================================================
    # Install Boundaries
    # =========================================================

    def _install_cancellation_boundaries(
        self,
    ) -> None:

        self._original_llm = (
            self.agent.llm
        )

        self._original_tool_executor = (
            self.agent
            .tool_executor
        )

        cancellable_llm = (
            CancellableLLMClient(
                client=(
                    self._original_llm
                ),
                token=(
                    self.token
                ),
            )
        )

        self.agent.llm = (
            cancellable_llm
        )

        # Planner and replanner must use the same cancellation
        # boundary as the main Agent.
        planner = getattr(
            self.agent,
            "planner",
            None,
        )

        if (
            planner
            is not None
            and hasattr(
                planner,
                "llm",
            )
        ):

            planner.llm = (
                cancellable_llm
            )

        replanner = getattr(
            self.agent,
            "replanner",
            None,
        )

        if (
            replanner
            is not None
            and hasattr(
                replanner,
                "llm",
            )
        ):

            replanner.llm = (
                cancellable_llm
            )

        self.agent.runtime = (
            CancellableToolExecutor(
                executor=(
                    self._original_tool_executor
                ),
                token=(
                    self.token
                ),
            )
        )

    # =========================================================
    # Restore
    # =========================================================

    def _restore_runtime(
        self,
    ) -> None:

        if (
            self._original_llm
            is not None
        ):

            self.agent.llm = (
                self._original_llm
            )

            planner = getattr(
                self.agent,
                "planner",
                None,
            )

            if (
                planner
                is not None
                and hasattr(
                    planner,
                    "llm",
                )
            ):

                planner.llm = (
                    self._original_llm
                )

            replanner = getattr(
                self.agent,
                "replanner",
                None,
            )

            if (
                replanner
                is not None
                and hasattr(
                    replanner,
                    "llm",
                )
            ):

                replanner.llm = (
                    self._original_llm
                )

        if (
            self._original_tool_executor
            is not None
        ):

            self.agent.runtime = (
                self._original_tool_executor
            )


# =============================================================
# Async Agent Runner
# =============================================================


class AsyncAgentRunner:
    """
    Start MiniCodex tasks as asynchronous background jobs.

    One MiniCodexAgent instance must only execute one task at a
    time because the Agent contains mutable task-local state:

        active_plan
        validation state
        checkpoints
        Git baseline
        Working Memory
        Trace recorder

    Concurrent jobs therefore require separate Agent instances.
    """

    def __init__(
        self,
        *,
        agent,
        poll_interval: float = 0.05,
    ):

        self.agent = (
            agent
        )

        self.poll_interval = max(
            0.01,
            float(
                poll_interval
            ),
        )

        self._active_task: (
            AsyncAgentTask
            | None
        ) = None

        self._lock = (
            threading.Lock()
        )

    # =========================================================
    # Start
    # =========================================================

    def start(
        self,
        user_input: str,
        *,
        use_planning: bool | None = None,
        policy=None,
    ) -> AsyncAgentTask:

        with self._lock:

            if (
                self._active_task
                is not None
                and not (
                    self._active_task
                    .done
                )
            ):

                raise RuntimeError(
                    (
                        "This MiniCodexAgent already "
                        "has a running task. "
                        "Use one Agent instance per "
                        "concurrent task."
                    )
                )

            token = (
                CancellationToken()
            )

            task = (
                AsyncAgentTask(
                    task_id=(
                        uuid.uuid4()
                        .hex
                    ),
                    agent=(
                        self.agent
                    ),
                    user_input=(
                        user_input
                    ),
                    use_planning=(
                        use_planning
                    ),
                    policy=policy,
                    token=(
                        token
                    ),
                    poll_interval=(
                        self.poll_interval
                    ),
                )
            )

            self._active_task = (
                task
            )

            task.start()

            return task

    # =========================================================
    # Convenience Run
    # =========================================================

    async def run(
        self,
        user_input: str,
        *,
        use_planning: bool | None = None,
        policy=None,
    ) -> AsyncTaskResult:

        task = (
            self.start(
                user_input,
                use_planning=(
                    use_planning
                ),
                policy=policy,
            )
        )

        return (
            await task.result()
        )

    # =========================================================
    # Active Task
    # =========================================================

    @property
    def active_task(
        self,
    ) -> (
        AsyncAgentTask
        | None
    ):

        return (
            self._active_task
        )
