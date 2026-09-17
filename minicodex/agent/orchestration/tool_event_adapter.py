"""Atomic provider tool-batch execution and control transitions."""

from __future__ import annotations

from dataclasses import dataclass

from ..editing import EditFailureType
from ..progress import ProgressKind, ProgressSignal
from ..reason_codes import ReasonCode
from ..task_state import AgentPhase, RuntimeEventType
from .message_protocol import close_tool_batch_before_control_transition
from .tool_call_runner import ToolCallRun, ToolCallRunner
from .tool_batch_result import ToolBatchResult
from .tool_result_handlers import EditResultHandler, ValidationResultHandler


class ToolEventAdapter:
    """Translate executed tool facts into domain events and control decisions."""

    def __init__(self, call_runner):
        self.call_runner = call_runner
        self.edit_handler = EditResultHandler()
        self.validation_handler = ValidationResultHandler()

    def process(self, agent, tool_call, *, index, tool_calls, messages,
                current_plan_step, runs, evidence_items, signals):
        self._emit_event(
            agent,
            RuntimeEventType.TOOL_STARTED,
            tool_name=tool_call.function.name,
        )
        run = self.call_runner.run(agent, tool_call)
        runs.append(run)
        tool_name, arguments, result = run.tool_name, run.arguments, run.result
        capabilities = (agent.registry.capabilities_for(tool_name)
                        if tool_name in getattr(agent.registry, "_tools", {}) else frozenset())
        is_edit = "code.edit" in capabilities
        if not is_edit and capabilities & {"process.run", "test.run", "service.validate", "validation.browser"}:
            previous_revision = agent.validation_pipeline.state.edit_revision
            refresh = getattr(agent, "refresh_workspace_facts", None)
            if refresh is not None:
                refresh()
            if agent.validation_pipeline.state.edit_revision != previous_revision:
                # Validators can run generators or race with an editor. Their
                # observation cannot prove the revision they changed mid-check.
                result.data["workspace_changed_during_validation"] = True
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
            return None

        controller = getattr(agent, "action_controller", None)
        if run.restriction is not None:
            if run.restriction.failure_type == "action_required_restriction":
                self._emit_event(agent, RuntimeEventType.PHASE_CHANGED, phase=AgentPhase.ACTING)
            metrics = getattr(agent, "execution_metrics", None)
            if metrics is not None and controller is not None:
                metrics.action_required_trigger_count = controller.action_required_trigger_count
            agent.plan_orchestrator.record_attempt_failure(current_plan_step)
            self._append_observation(messages, tool_call.id, result, "Tool Restriction")
            signal = ProgressSignal(ProgressKind.NONE, "Tool call was restricted.")
            signals.append(signal)
            self._observe(agent, tool_name, signal)
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

        metrics = getattr(agent, "execution_metrics", None)
        if run.duplicate_blocked:
            agent.plan_orchestrator.record_attempt_failure(current_plan_step)
            if metrics is not None:
                metrics.repeated_action_count += 1
            print("\n[Duplicate Tool Blocked]")
        elif not result.success:
            agent.plan_orchestrator.record_attempt_failure(current_plan_step)
            failure_type = str(result.data.get("failure_type", "") or "")
            if failure_type in {
                "safety_blocked", "permission_denied", "workspace_conflict",
                "rollback_conflict", "missing_credential", "environment_failure",
            }:
                agent.concrete_blockers.append(
                    f"{failure_type}: {result.error or result.summary}"
                )

        current_revision = agent.validation_pipeline.state.edit_revision
        recorded_revision = (
            current_revision + 1
            if is_edit and result.success
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
        if metrics is not None:
            metrics.record_tool(
                tool_name,
                llm_call_count=agent.token_metrics.call_count,
                arguments=arguments,
                success=result.success,
                revision=current_revision,
                capabilities=capabilities,
            )

        retry = getattr(agent, "edit_retry", None)
        retry_message = retry.observe(tool_name, arguments, result) if retry is not None else None
        if retry_message:
            stale = str(result.data.get("edit_failure_type", result.data.get("failure_type", ""))) == EditFailureType.STALE_CONTEXT.value
            self._emit_event(
                agent,
                RuntimeEventType.RECOVERY_STARTED,
                level=1,
                failure_type="stale_context" if stale else "edit_failure",
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

        # Registered tools are classified only through their capabilities.  A
        # few embedding/test executors intentionally run outside a registry;
        # their structured validation result remains sufficient to dispatch the
        # result handler without reviving a tool-name fallback.
        structured_validation_result = (
            str(result.data.get("outcome", "")).casefold() in {"passed", "failed", "inconclusive"}
            and "errors" in result.data
        )
        is_validation = (bool(capabilities & {"test.run", "validation.static_web", "validation.browser", "service.validate", "validation.semantic"})
            or ("process.run" in capabilities and arguments.get("purpose") in {"acceptance", "regression"})
            or structured_validation_result
        )
        if (
            not is_validation
            and is_edit
            and not result.success
        ):
            self._emit_event(agent, RuntimeEventType.PHASE_CHANGED, phase=AgentPhase.ACTING)
        if not is_edit and hasattr(agent, "step_evidence"):
            agent.step_evidence.record(
                step_id=current_plan_step.id if current_plan_step else None,
                edit_revision=agent.validation_pipeline.state.edit_revision,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
            )

        signal = ProgressSignal(ProgressKind.OBSERVATION, "Tool produced an observation.")
        if is_edit and result.success:
            signal, completed = self.edit_handler.apply(
                agent, tool_name=tool_name, arguments=arguments, result=result,
                current_plan_step=current_plan_step, emit=self._emit_event,
            )
            print(f"\n[Edit Applied]\n[Validation Revision] {agent.validation_pipeline.state.edit_revision}")
            checkpoint_id = result.data.get("checkpoint_id")
            if checkpoint_id:
                print(f"[Checkpoint] {checkpoint_id}")
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

        if tool_name == "replan" and result.data.get("replanned"):
            signal = ProgressSignal(ProgressKind.ADVANCED, "Plan was revised.")

        if is_validation:
            handled = self.validation_handler.apply(
                agent, tool_name=tool_name, arguments=arguments, result=result,
                capabilities=capabilities, metrics=metrics, emit=self._emit_event,
            )
            if handled.evidence is not None:
                evidence_items.append(handled.evidence)
                print(f"\n[Validation Evidence]\nRevision: {handled.evidence.edit_revision}"
                      f"\nScope: {handled.evidence.scope.value}\nPurpose: {handled.evidence.purpose.value}"
                      f"\nOutcome: {handled.evidence.outcome.value}")
            signal, decision = handled.signal, handled.decision
            if handled.completed_plan and decision is not None:
                decision = type(decision)(restart=True, early_stop=decision.early_stop,
                                          followup_message=decision.followup_message,
                                          skipped_reason=decision.skipped_reason, reason_code=decision.reason_code)
            signals.append(signal)
            self._observe(agent, tool_name, signal)
            finished = self._check_completion(agent, messages, tool_calls[index + 1 :])
            if finished is not None:
                return ToolBatchResult(tuple(runs), tuple(evidence_items), tuple(signals),
                                       early_stop=finished, completion_finished=True)
            if decision is not None and (decision.early_stop or decision.restart):
                self._close(messages, tool_calls[index + 1 :],
                            decision.skipped_reason or "validation changed agent loop control flow",
                            decision.followup_message)
                return ToolBatchResult(tuple(runs), tuple(evidence_items), tuple(signals),
                                       restart=decision.restart, early_stop=decision.early_stop,
                                       followup_message=decision.followup_message, reason_code=decision.reason_code)
            return None

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

        if tool_name == "replan" and result.data.get("replanned"):
            self._close(
                messages,
                tool_calls[index + 1 :],
                "the plan changed and remaining calls used the previous plan",
            )
            return ToolBatchResult(tuple(runs), tuple(evidence_items), tuple(signals), restart=True)

        return None

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
            metrics = getattr(agent, "execution_metrics", None)
            if metrics is not None and signal.kind == ProgressKind.NONE:
                metrics.no_progress_detections += 1
            ToolEventAdapter._emit_event(
                agent,
                RuntimeEventType.TOOL_FINISHED,
                tool_name=tool_name,
                progress_kind=signal.kind.value,
                consecutive_inspections=controller.consecutive_inspections,
                consecutive_no_state_change=controller.consecutive_no_state_change,
            )

    @staticmethod
    def _emit_event(agent, kind: RuntimeEventType, **data) -> None:
        emit = getattr(agent, "apply_runtime_event", None)
        if callable(emit):
            emit(kind, **data)

    @staticmethod
    def _check_completion(agent, messages, remaining) -> str | None:
        checking = getattr(agent, "check_completion_after_batch", None)
        handling = checking() if callable(checking) else None
        if handling is None:
            return None
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
        capabilities = (agent.registry.capabilities_for(tool_name)
                        if tool_name in getattr(agent.registry, "_tools", {}) else frozenset())
        if "file.read" in capabilities:
            emit(f"Reading {path or 'target'}...")
        elif "code.edit" in capabilities:
            emit(f"Editing {path or 'target'}...")
        elif "test.run" in capabilities:
            emit("Running focused tests...")
            if result.success and result.data.get("tests_passed") is True:
                emit(f"{int(result.data.get('passed', 0) or 0)} tests passed.")
        elif capabilities & {"validation.static_web", "validation.browser", "service.validate"}:
            emit(f"Validating {path or 'web artifact'}...")
            if result.success and result.data.get("outcome") == "passed":
                emit("Validation passed.")
