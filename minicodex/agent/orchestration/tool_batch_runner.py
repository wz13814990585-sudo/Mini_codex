"""Atomic provider tool-batch execution and control transitions."""

from __future__ import annotations

from dataclasses import dataclass

from ..editing import EditFailureType
from ..progress import ProgressKind, ProgressSignal
from ..reason_codes import ReasonCode
from .message_protocol import close_tool_batch_before_control_transition
from .tool_call_runner import ToolCallRun, ToolCallRunner


EDIT_TOOL_NAMES = frozenset({"patch_file", "replace_lines", "replace_symbol", "write_file"})


@dataclass(frozen=True)
class ToolBatchResult:
    runs: tuple[ToolCallRun, ...]
    validation_evidence: tuple = ()
    progress_signals: tuple[ProgressSignal, ...] = ()
    restart: bool = False
    early_stop: str | None = None
    followup_message: str | None = None
    completion_finished: bool = False
    reason_code: ReasonCode | None = None


class ToolBatchRunner:
    """Own complete ordered batches and provider-message atomicity."""

    def __init__(self, call_runner: ToolCallRunner | None = None) -> None:
        self.call_runner = call_runner or ToolCallRunner()

    # Compatibility for callers that exercised the former one-call runner.
    def run_call(self, agent, tool_call) -> ToolCallRun:
        return self.call_runner.run(agent, tool_call)

    def run(self, agent, assistant_message, messages: list, current_plan_step=None) -> ToolBatchResult:
        tool_calls = list(getattr(assistant_message, "tool_calls", None) or ())
        messages.append(assistant_message.model_dump(exclude_none=True))
        runs: list[ToolCallRun] = []
        evidence_items: list = []
        signals: list[ProgressSignal] = []

        for index, tool_call in enumerate(tool_calls):
            run = self.call_runner.run(agent, tool_call)
            runs.append(run)
            tool_name, arguments, result = run.tool_name, run.arguments, run.result
            self._emit_normal_progress(agent, tool_name, arguments, result)
            print(f"\n[Tool] {tool_name}")
            if arguments:
                print(f"[Arguments] {arguments}")

            if run.preparation_failed:
                agent.working_summary.record_tool_result(tool_name=tool_name, arguments={}, result=result)
                agent.plan_orchestrator.record_attempt_failure(current_plan_step)
                self._append_observation(messages, tool_call.id, result, "Tool Preparation Failed")
                signal = ProgressSignal(ProgressKind.NONE, "Tool preparation failed.")
                signals.append(signal)
                self._observe(agent, tool_name, signal)
                continue

            controller = getattr(agent, "action_controller", None)
            if run.restriction is not None:
                if run.restriction.failure_type == "action_required_restriction":
                    agent.task_state.require_action()
                metrics = getattr(agent, "execution_metrics", None)
                if metrics is not None and controller is not None:
                    metrics.action_required_trigger_count = controller.action_required_trigger_count
                agent.plan_orchestrator.record_attempt_failure(current_plan_step)
                self._append_observation(messages, tool_call.id, result, "Tool Restriction")
                self._close(
                    messages,
                    tool_calls[index + 1 :],
                    "execution policy restricted the current tool batch",
                    run.restriction.reason,
                )
                return ToolBatchResult(
                    tuple(runs), tuple(evidence_items), tuple(signals),
                    restart=True, followup_message=run.restriction.reason,
                )

            if run.duplicate_blocked:
                agent.plan_orchestrator.record_attempt_failure(current_plan_step)
                print("\n[Duplicate Tool Blocked]")
            elif not result.success:
                agent.plan_orchestrator.record_attempt_failure(current_plan_step)

            current_revision = agent.validation_pipeline.state.edit_revision
            recorded_revision = (
                current_revision + 1
                if tool_name in EDIT_TOOL_NAMES and result.success
                else current_revision
            )
            agent.working_summary.record_tool_result(
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                revision=recorded_revision,
            )
            if tool_name == "search_symbol" and result.success:
                agent.latest_symbol_recovery_paths = tuple(
                    dict.fromkeys(
                        str(match.get("path", "")).strip()
                        for match in (result.data.get("matches", ()) or ())
                        if str(match.get("path", "")).strip()
                    )
                )
            self._append_observation(messages, tool_call.id, result)
            metrics = getattr(agent, "execution_metrics", None)
            if metrics is not None:
                metrics.record_tool(
                    tool_name,
                    llm_call_count=agent.token_metrics.call_count,
                    arguments=arguments,
                    success=result.success,
                )

            retry = getattr(agent, "edit_retry", None)
            retry_message = retry.observe(tool_name, arguments, result) if retry is not None else None
            if retry_message:
                stale = str(result.data.get("edit_failure_type", result.data.get("failure_type", ""))) == EditFailureType.STALE_CONTEXT.value
                agent.task_state.transition_for_tool(
                    tool_name, success=result.success, stale_edit=stale
                )
                signal = ProgressSignal(ProgressKind.NONE, "Bounded local edit recovery is required.")
                signals.append(signal)
                self._observe(agent, tool_name, signal)
                self._close(
                    messages,
                    tool_calls[index + 1 :],
                    "bounded edit recovery changed the next allowed action",
                    retry_message,
                )
                return ToolBatchResult(
                    tuple(runs), tuple(evidence_items), tuple(signals),
                    restart=True, followup_message=retry_message,
                )

            is_validation = self._is_validation(tool_name, arguments)
            if not is_validation and not (tool_name in EDIT_TOOL_NAMES and result.success):
                agent.task_state.transition_for_tool(tool_name, success=result.success)
            if tool_name not in EDIT_TOOL_NAMES and hasattr(agent, "step_evidence"):
                agent.step_evidence.record(
                    step_id=current_plan_step.id if current_plan_step else None,
                    edit_revision=agent.validation_pipeline.state.edit_revision,
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                )

            signal = ProgressSignal(ProgressKind.OBSERVATION, "Tool produced an observation.")
            if tool_name in EDIT_TOOL_NAMES and result.success:
                revision = agent.validation_pipeline.record_edit()
                agent.task_state.transition_for_tool(tool_name, success=True)
                if hasattr(agent, "step_evidence"):
                    agent.step_evidence.record(
                        step_id=current_plan_step.id if current_plan_step else None,
                        edit_revision=revision,
                        tool_name=tool_name,
                        arguments=arguments,
                        result=result,
                    )
                agent.progress.mark_meaningful_progress()
                signal = ProgressSignal(ProgressKind.ADVANCED, f"Edit created revision {revision}.")
                print(f"\n[Edit Applied]\n[Validation Revision] {revision}")
                checkpoint_id = result.data.get("checkpoint_id")
                if checkpoint_id:
                    print(f"[Checkpoint] {checkpoint_id}")
                _, completed = agent.plan_orchestrator.reconcile(agent)
                if completed:
                    self._observe(agent, tool_name, signal)
                    signals.append(signal)
                    finished = self._check_completion(agent, messages, tool_calls[index + 1 :])
                    if finished is not None:
                        return ToolBatchResult(
                            tuple(runs),
                            tuple(evidence_items),
                            tuple(signals),
                            early_stop=finished,
                            completion_finished=True,
                        )
                    self._close(
                        messages,
                        tool_calls[index + 1 :],
                        "machine-checkable plan criteria advanced the active plan",
                    )
                    return ToolBatchResult(tuple(runs), tuple(evidence_items), tuple(signals), restart=True)

            if tool_name == "complete_plan_step" and result.data.get("completed"):
                signal = ProgressSignal(ProgressKind.ADVANCED, "Plan step completed.")
            elif tool_name == "replan" and result.data.get("replanned"):
                signal = ProgressSignal(ProgressKind.ADVANCED, "Plan was revised.")

            if is_validation:
                evidence = agent.validation_pipeline.observe(
                    tool_name=tool_name, arguments=arguments, result=result
                )
                if evidence is not None:
                    evidence_items.append(evidence)
                    agent.task_progress_state()
                    agent.task_state.transition_for_tool(
                        tool_name,
                        success=result.success,
                        validation_outcome=evidence.outcome,
                    )
                    _, completed = agent.plan_orchestrator.reconcile(agent)
                    print(
                        f"\n[Validation Evidence]\nRevision: {evidence.edit_revision}"
                        f"\nScope: {evidence.scope.value}\nPurpose: {evidence.purpose.value}"
                        f"\nOutcome: {evidence.outcome.value}"
                    )
                    decision = agent.validation_orchestrator.apply(agent=agent, evidence=evidence)
                    signal = agent.latest_progress_signal or ProgressSignal(
                        ProgressKind.NONE, "Validation did not yield comparable progress."
                    )
                    if completed:
                        decision = type(decision)(
                            restart=True,
                            early_stop=decision.early_stop,
                            followup_message=decision.followup_message,
                            skipped_reason=decision.skipped_reason,
                            reason_code=decision.reason_code,
                        )
                    signals.append(signal)
                    self._observe(agent, tool_name, signal)
                    finished = self._check_completion(agent, messages, tool_calls[index + 1 :])
                    if finished is not None:
                        return ToolBatchResult(
                            tuple(runs),
                            tuple(evidence_items),
                            tuple(signals),
                            early_stop=finished,
                            completion_finished=True,
                        )
                    if decision.early_stop or decision.restart:
                        self._close(
                            messages,
                            tool_calls[index + 1 :],
                            decision.skipped_reason or "validation changed agent loop control flow",
                            decision.followup_message,
                        )
                        return ToolBatchResult(
                            tuple(runs), tuple(evidence_items), tuple(signals),
                            restart=decision.restart,
                            early_stop=decision.early_stop,
                            followup_message=decision.followup_message,
                            reason_code=decision.reason_code,
                        )
                    continue

            signals.append(signal)
            self._observe(agent, tool_name, signal)
            if signal.advanced:
                finished = self._check_completion(agent, messages, tool_calls[index + 1 :])
                if finished is not None:
                    return ToolBatchResult(
                        tuple(runs),
                        tuple(evidence_items),
                        tuple(signals),
                        early_stop=finished,
                        completion_finished=True,
                    )

            if tool_name == "complete_plan_step" and result.data.get("completed"):
                self._close(
                    messages,
                    tool_calls[index + 1 :],
                    "the active plan step completed and remaining calls used stale plan context",
                )
                return ToolBatchResult(tuple(runs), tuple(evidence_items), tuple(signals), restart=True)
            if tool_name == "replan" and result.data.get("replanned"):
                self._close(
                    messages,
                    tool_calls[index + 1 :],
                    "the plan changed and remaining calls used the previous plan",
                )
                return ToolBatchResult(tuple(runs), tuple(evidence_items), tuple(signals), restart=True)

        return ToolBatchResult(tuple(runs), tuple(evidence_items), tuple(signals))

    @staticmethod
    def _is_validation(tool_name: str, arguments: dict) -> bool:
        return tool_name in {"run_tests", "validate_static_web", "validate_browser_app"} or (
            tool_name == "run_command"
            and str(arguments.get("purpose", "diagnostic")).strip().lower() == "acceptance"
        )

    @staticmethod
    def _append_observation(messages, call_id, result, heading=None) -> None:
        text = result.to_llm_text()
        if heading:
            print(f"\n[{heading}]")
        print(f"\n[Observation]\n{text}")
        messages.append({"role": "tool", "tool_call_id": call_id, "content": text})

    @staticmethod
    def _close(messages, remaining, reason, followup=None) -> None:
        close_tool_batch_before_control_transition(
            messages, remaining, reason, followup_user_message=followup
        )

    @staticmethod
    def _observe(agent, tool_name: str, signal: ProgressSignal) -> None:
        controller = getattr(agent, "action_controller", None)
        if controller is not None:
            controller.observe_action(tool_name, agent.task_progress_state(), signal)

    @staticmethod
    def _check_completion(agent, messages, remaining) -> str | None:
        handling = agent.completion_handler.check_after_batch(agent)
        if not handling.finished:
            return None
        close_tool_batch_before_control_transition(
            messages,
            remaining,
            "deterministic completion became ready during the tool batch",
        )
        return handling.output or ""

    @staticmethod
    def _emit_normal_progress(agent, tool_name: str, arguments: dict, result) -> None:
        emit = getattr(agent, "emit_normal_progress", None)
        if not callable(emit):
            return
        path = str(arguments.get("path", "") or "").strip()
        if tool_name == "read_file":
            emit(f"Reading {path or 'target'}...")
        elif tool_name in EDIT_TOOL_NAMES:
            emit(f"Editing {path or 'target'}...")
        elif tool_name == "run_tests":
            emit("Running focused tests...")
            if result.success and result.data.get("tests_passed") is True:
                emit(f"{int(result.data.get('passed', 0) or 0)} tests passed.")
        elif tool_name in {"validate_static_web", "validate_browser_app"}:
            emit(f"Validating {path or 'web artifact'}...")
            if result.success and result.data.get("outcome") == "passed":
                emit("Validation passed.")
