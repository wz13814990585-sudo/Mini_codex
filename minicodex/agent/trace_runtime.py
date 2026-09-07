"""Runtime tracing adapters for MiniCodex."""

from __future__ import annotations

from types import MethodType
import time

from .trace import (
    TraceEventType,
    TraceRecorder,
)


EDIT_TOOL_NAMES = {
    "patch_file",
    "replace_lines",
    "replace_symbol",
    "write_file",
}


# =============================================================
# Tracing LLM
# =============================================================


class TracingLLMClient:
    """
    Observe LLM calls without changing the underlying client.
    """

    def __init__(
        self,
        *,
        client,
        recorder: TraceRecorder,
    ):

        self.client = (
            client
        )

        self.recorder = (
            recorder
        )

    def chat(
        self,
        *args,
        **kwargs,
    ):

        messages = (
            kwargs.get(
                "messages"
            )
        )

        tools = (
            kwargs.get(
                "tools"
            )
        )

        started = (
            time.perf_counter()
        )

        self._safe_emit(
            TraceEventType.LLM_STARTED,
            {
                "message_count": (
                    len(
                        messages
                    )
                    if messages
                    is not None
                    else None
                ),
                "tool_schema_count": (
                    len(
                        tools
                    )
                    if tools
                    is not None
                    else None
                ),
            },
        )

        try:

            response = (
                self.client
                .chat(
                    *args,
                    **kwargs,
                )
            )

        except Exception as e:

            duration = (
                time.perf_counter()
                - started
            )

            self._safe_emit(
                TraceEventType.LLM_FAILED,
                {
                    "duration_seconds": (
                        duration
                    ),
                    "error": (
                        f"{type(e).__name__}: "
                        f"{e}"
                    ),
                },
            )

            raise

        duration = (
            time.perf_counter()
            - started
        )

        usage = getattr(
            response,
            "usage",
            None,
        )

        message = getattr(
            response,
            "message",
            None,
        )

        tool_calls = getattr(
            message,
            "tool_calls",
            None,
        )

        self._safe_emit(
            TraceEventType.LLM_FINISHED,
            {
                "duration_seconds": (
                    duration
                ),
                "prompt_tokens": (
                    getattr(
                        usage,
                        "prompt_tokens",
                        0,
                    )
                ),
                "completion_tokens": (
                    getattr(
                        usage,
                        "completion_tokens",
                        0,
                    )
                ),
                "total_tokens": (
                    getattr(
                        usage,
                        "total_tokens",
                        0,
                    )
                ),
                "tool_call_count": (
                    len(
                        tool_calls
                    )
                    if tool_calls
                    else 0
                ),
                "returned_final_text": (
                    not bool(
                        tool_calls
                    )
                ),
            },
        )

        return response

    def _safe_emit(
        self,
        event_type,
        data,
    ) -> None:

        try:

            self.recorder.emit(
                event_type,
                data,
            )

        except Exception:

            pass

    def __getattr__(
        self,
        name,
    ):

        return getattr(
            self.client,
            name,
        )


# =============================================================
# Tracing Tool Executor
# =============================================================


class TracingToolExecutor:
    """
    Observe one prepared tool execution.

    The wrapped executor may itself contain:

        SafetyToolExecutor
            ↓
        CheckpointingToolExecutor
            ↓
        ToolExecutor
    """

    def __init__(
        self,
        *,
        executor,
        recorder: TraceRecorder,
    ):

        self.executor = (
            executor
        )

        self.recorder = (
            recorder
        )

    def prepare(
        self,
        tool_name: str,
        raw_arguments: str,
    ):

        return (
            self.executor
            .prepare(
                tool_name=tool_name,
                raw_arguments=raw_arguments,
            )
        )

    def execute_prepared(
        self,
        prepared,
    ):

        self._safe_emit(
            TraceEventType.TOOL_REQUESTED,
            {
                "tool_name": (
                    prepared.tool_name
                ),
                "arguments": (
                    prepared.arguments
                ),
                "preparation_failed": (
                    prepared.error
                    is not None
                ),
            },
        )

        started = (
            time.perf_counter()
        )

        try:

            execution = (
                self.executor
                .execute_prepared(
                    prepared
                )
            )

        except Exception as e:

            duration = (
                time.perf_counter()
                - started
            )

            self._safe_emit(
                TraceEventType.TOOL_FINISHED,
                {
                    "tool_name": (
                        prepared.tool_name
                    ),
                    "success": False,
                    "duration_seconds": (
                        duration
                    ),
                    "exception": (
                        f"{type(e).__name__}: "
                        f"{e}"
                    ),
                },
            )

            raise

        duration = (
            time.perf_counter()
            - started
        )

        result = (
            execution.result
        )

        result_data = (
            result.data
            or {}
        )

        # =====================================================
        # Safety Decision
        # =====================================================

        safety = (
            result_data
            .get(
                "safety"
            )
        )

        if isinstance(
            safety,
            dict,
        ):

            self._safe_emit(
                TraceEventType.SAFETY_DECISION,
                {
                    "tool_name": (
                        prepared.tool_name
                    ),
                    **safety,
                },
            )

        # =====================================================
        # Tool Finished
        # =====================================================

        self._safe_emit(
            TraceEventType.TOOL_FINISHED,
            {
                "tool_name": (
                    prepared.tool_name
                ),
                "arguments": (
                    prepared.arguments
                ),
                "success": (
                    result.success
                ),
                "duration_seconds": (
                    duration
                ),
                "summary": (
                    result.summary
                ),
                "failure_type": (
                    result_data
                    .get(
                        "failure_type"
                    )
                ),
            },
        )

        # =====================================================
        # Edit
        # =====================================================

        if (
            prepared.tool_name
            in EDIT_TOOL_NAMES
            and result.success
        ):

            self._safe_emit(
                TraceEventType.EDIT_APPLIED,
                {
                    "tool_name": (
                        prepared.tool_name
                    ),
                    "path": (
                        prepared.arguments
                        .get(
                            "path"
                        )
                    ),
                    "checkpoint_id": (
                        result_data
                        .get(
                            "checkpoint_id"
                        )
                    ),
                    "checkpoint_revision": (
                        result_data
                        .get(
                            "checkpoint_revision"
                        )
                    ),
                    "checkpoint_sealed": (
                        result_data
                        .get(
                            "checkpoint_sealed"
                        )
                    ),
                    "safety_degraded": (
                        result_data
                        .get(
                            "safety_degraded"
                        )
                    ),
                },
            )

        # =====================================================
        # Validation
        # =====================================================

        if (
            prepared.tool_name
            in {
                "run_tests",
                "validate_static_web",
            }
        ):

            self._safe_emit(
                TraceEventType.VALIDATION_RUN,
                {
                    "success": (
                        result.success
                    ),
                    "path": (
                        prepared.arguments
                        .get(
                            "path"
                        )
                    ),
                    "purpose": (
                        prepared.arguments.get("purpose")
                        or (
                            "acceptance"
                            if prepared.tool_name
                            == "validate_static_web"
                            else None
                        )
                    ),
                    "outcome": result_data.get(
                        "outcome"
                    ),
                    "passed": (
                        result_data
                        .get(
                            "passed"
                        )
                    ),
                    "failed": (
                        result_data
                        .get(
                            "failed"
                        )
                    ),
                    "errors": (
                        result_data
                        .get(
                            "errors"
                        )
                    ),
                    "skipped": (
                        result_data
                        .get(
                            "skipped"
                        )
                    ),
                },
            )

        return execution

    def _safe_emit(
        self,
        event_type,
        data,
    ) -> None:

        try:

            self.recorder.emit(
                event_type,
                data,
            )

        except Exception:

            # Observability must never alter execution.
            pass


# =============================================================
# Tracing Rollback Engine
# =============================================================


class TracingRollbackEngine:

    def __init__(
        self,
        *,
        engine,
        recorder: TraceRecorder,
    ):

        self.engine = (
            engine
        )

        self.recorder = (
            recorder
        )

    def rollback(
        self,
        checkpoint_id: str,
    ):

        self._safe_emit(
            TraceEventType.ROLLBACK_STARTED,
            {
                "checkpoint_id": (
                    checkpoint_id
                ),
            },
        )

        started = (
            time.perf_counter()
        )

        try:

            result = (
                self.engine
                .rollback(
                    checkpoint_id
                )
            )

        except Exception as e:

            self._safe_emit(
                TraceEventType.ROLLBACK_FINISHED,
                {
                    "checkpoint_id": (
                        checkpoint_id
                    ),
                    "success": False,
                    "duration_seconds": (
                        time.perf_counter()
                        - started
                    ),
                    "exception": (
                        f"{type(e).__name__}: "
                        f"{e}"
                    ),
                },
            )

            raise

        self._safe_emit(
            TraceEventType.ROLLBACK_FINISHED,
            {
                "checkpoint_id": (
                    checkpoint_id
                ),
                "success": (
                    result.success
                ),
                "duration_seconds": (
                    time.perf_counter()
                    - started
                ),
                "path": (
                    result.data
                    .get(
                        "path"
                    )
                ),
                "failure_type": (
                    result.data
                    .get(
                        "failure_type"
                    )
                ),
            },
        )

        return result

    def _safe_emit(
        self,
        event_type,
        data,
    ) -> None:

        try:

            self.recorder.emit(
                event_type,
                data,
            )

        except Exception:

            pass

    def __getattr__(
        self,
        name,
    ):

        return getattr(
            self.engine,
            name,
        )


# =============================================================
# Attach Runtime Tracing
# =============================================================


def attach_runtime_tracing(
    agent,
    *,
    recorder: TraceRecorder,
):
    """
    Attach tracing to an existing MiniCodexAgent without
    changing its orchestration semantics.

    Returns the same Agent object.
    """

    if getattr(
        agent,
        "_runtime_trace_attached",
        False,
    ):

        return agent

    agent.trace_recorder = (
        recorder
    )

    # =========================================================
    # LLM
    # =========================================================

    if not isinstance(
        agent.llm,
        TracingLLMClient,
    ):

        traced_llm = (
            TracingLLMClient(
                client=(
                    agent.llm
                ),
                recorder=(
                    recorder
                ),
            )
        )

        agent.llm = (
            traced_llm
        )

        planner = getattr(
            agent,
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
                traced_llm
            )

        replanner = getattr(
            agent,
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
                traced_llm
            )

    # =========================================================
    # Tool Executor
    # =========================================================

    if not isinstance(
        agent.tool_executor,
        TracingToolExecutor,
    ):

        agent.tool_executor = (
            TracingToolExecutor(
                executor=(
                    agent.tool_executor
                ),
                recorder=(
                    recorder
                ),
            )
        )

    # =========================================================
    # Rollback
    # =========================================================

    rollback_engine = getattr(
        agent,
        "rollback_engine",
        None,
    )

    if (
        rollback_engine
        is not None
        and not isinstance(
            rollback_engine,
            TracingRollbackEngine,
        )
    ):

        agent.rollback_engine = (
            TracingRollbackEngine(
                engine=(
                    rollback_engine
                ),
                recorder=(
                    recorder
                ),
            )
        )

    # =========================================================
    # Task Run
    # =========================================================

    original_run = (
        agent.run
    )

    def traced_run(
        self,
        user_input: str,
        use_planning: bool | None = None,
        policy=None,
    ):

        recorder.start_task(
            prompt=(
                user_input
            )
        )

        started = (
            time.perf_counter()
        )

        try:

            run_kwargs = {"use_planning": use_planning}
            if policy is not None:
                run_kwargs["policy"] = policy
            output = original_run(user_input, **run_kwargs)

        except Exception as e:

            _safe_emit(
                recorder,
                TraceEventType.TASK_FAILED,
                {
                    "duration_seconds": (
                        time.perf_counter()
                        - started
                    ),
                    "error": (
                        f"{type(e).__name__}: "
                        f"{e}"
                    ),
                },
            )

            raise

        validation_pipeline = getattr(
            self,
            "validation_pipeline",
            None,
        )

        validation_state = getattr(
            validation_pipeline,
            "state",
            None,
        )

        plan = getattr(
            self,
            "active_plan",
            None,
        )

        if (
            plan
            is None
        ):

            plan_completed = True

        else:

            try:

                plan_completed = bool(
                    plan.is_completed()
                )

            except Exception:

                plan_completed = False

        _safe_emit(
            recorder,
            TraceEventType.TASK_FINISHED,
            {
                "execution_mode": getattr(
                    getattr(self, "execution_metrics", None),
                    "execution_mode",
                    None,
                ),
                "duration_seconds": (
                    time.perf_counter()
                    - started
                ),
                "output_length": (
                    len(
                        str(
                            output
                        )
                    )
                ),
                "edit_revision": (
                    getattr(
                        validation_state,
                        "edit_revision",
                        0,
                    )
                ),
                "has_edit": (
                    getattr(
                        validation_state,
                        "has_edit",
                        False,
                    )
                ),
                "acceptance_passed": (
                    getattr(
                        validation_state,
                        "acceptance_passed",
                        False,
                    )
                ),
                "full_validation_passed": (
                    getattr(
                        validation_state,
                        "full_passed",
                        False,
                    )
                ),
                "plan_completed": (
                    plan_completed
                ),
                "inspection_tool_count": getattr(
                    getattr(self, "execution_metrics", None),
                    "inspection_tool_count",
                    0,
                ),
                "edit_tool_count": getattr(
                    getattr(self, "execution_metrics", None),
                    "edit_tool_count",
                    0,
                ),
                "validation_tool_count": getattr(
                    getattr(self, "execution_metrics", None),
                    "validation_tool_count",
                    0,
                ),
                "calls_before_first_edit": getattr(
                    getattr(self, "execution_metrics", None),
                    "calls_before_first_edit",
                    None,
                ),
                "action_required_trigger_count": getattr(
                    getattr(self, "execution_metrics", None),
                    "action_required_trigger_count",
                    0,
                ),
                "final_outcome": getattr(
                    getattr(self, "execution_metrics", None),
                    "final_outcome",
                    None,
                ),
                "final_completion_reason": getattr(
                    getattr(self, "execution_metrics", None),
                    "final_completion_reason",
                    None,
                ),
            },
        )

        return output

    agent.run = (
        MethodType(
            traced_run,
            agent,
        )
    )

    # =========================================================
    # Replan
    # =========================================================

    original_replan = (
        agent.replan
    )

    def traced_replan(
        self,
        reason: str,
    ):

        _safe_emit(
            recorder,
            TraceEventType.REPLAN_STARTED,
            {
                "reason": (
                    reason
                ),
            },
        )

        result = (
            original_replan(
                reason
            )
        )

        _safe_emit(
            recorder,
            TraceEventType.REPLAN_FINISHED,
            {
                "reason": (
                    reason
                ),
                "replanned": (
                    bool(
                        result.get(
                            "replanned",
                            False,
                        )
                    )
                    if isinstance(
                        result,
                        dict,
                    )
                    else False
                ),
            },
        )

        return result

    agent.replan = (
        MethodType(
            traced_replan,
            agent,
        )
    )

    # =========================================================
    # Plan Step
    # =========================================================

    original_complete_plan_step = (
        agent.complete_plan_step
    )

    def traced_complete_plan_step(
        self,
    ):

        result = (
            original_complete_plan_step()
        )

        if (
            isinstance(
                result,
                dict,
            )
            and result.get(
                "completed",
                False,
            )
        ):

            _safe_emit(
                recorder,
                (
                    TraceEventType
                    .PLAN_STEP_COMPLETED
                ),
                {
                    "step_id": (
                        result.get(
                            "step_id"
                        )
                    ),
                    "description": (
                        result.get(
                            "step_description"
                        )
                    ),
                },
            )

        return result

    agent.complete_plan_step = (
        MethodType(
            traced_complete_plan_step,
            agent,
        )
    )

    agent._runtime_trace_attached = (
        True
    )

    return agent


# =============================================================
# Safe Trace Emit
# =============================================================


def _safe_emit(
    recorder,
    event_type,
    data,
) -> None:

    try:

        recorder.emit(
            event_type,
            data,
        )

    except Exception:

        pass
