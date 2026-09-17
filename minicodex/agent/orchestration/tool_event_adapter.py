"""Atomic provider tool-batch execution and control transitions."""

from __future__ import annotations

from dataclasses import dataclass

from ..editing import EditFailureType
from ..progress import ProgressKind, ProgressSignal
from ..reason_codes import ReasonCode
from ..task_state import AgentPhase, RuntimeEventType
from ..validation.plan import RequirementEvidenceResolver
from .message_protocol import close_tool_batch_before_control_transition
from .tool_call_runner import ToolCallRun, ToolCallRunner
from .tool_batch_result import ToolBatchResult


EDIT_TOOL_NAMES = frozenset({"patch_file", "replace_lines", "replace_symbol", "write_file"})



class ToolEventAdapter:
    """Translate executed tool facts into domain events and control decisions."""

    def __init__(self, call_runner):
        self.call_runner = call_runner

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
        is_edit = "code.edit" in capabilities or tool_name in EDIT_TOOL_NAMES
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

        is_validation = (bool(capabilities & {"test.run", "validation.static_web", "validation.browser", "service.validate"})
            or ("process.run" in capabilities and arguments.get("purpose") in {"acceptance", "regression"})
            or self._is_validation(tool_name, arguments))
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
            revision = agent.validation_pipeline.record_edit()
            requirements = getattr(agent, "task_requirements", None)
            if requirements is not None:
                requirements.invalidate_revision(revision)
                agent.sync_requirements_state()
            agent.working_summary.advance_revision(revision)
            agent._repo_map_initialized = False
            agent._repo_map_revision = None
            agent.workspace_session.invalidate(str(arguments.get("path", "")))
            # Latest keyed repository observations cannot survive mutation.
            memory = getattr(getattr(agent, "working_summary", None), "memory", None)
            if memory is not None:
                try:
                    memory.invalidate_path(str(arguments.get("path", "")))
                except Exception:
                    pass
            self._emit_event(
                agent,
                RuntimeEventType.EDIT_APPLIED,
                edit_revision=revision,
                path=str(arguments.get("path", "")),
                diff_quality_issues=result.data.get("diff_quality_issues", ()),
            )
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

        if tool_name == "replan" and result.data.get("replanned"):
            signal = ProgressSignal(ProgressKind.ADVANCED, "Plan was revised.")

        if is_validation:
            if "test.run" in capabilities:
                target = str(arguments.get("path", "")).split("::", 1)[0]
                changed_tests = [c for c in agent.checkpoint_manager.all_checkpoints()
                                 if c.sealed and not c.rolled_back and c.snapshot.path == target]
                if changed_tests:
                    result.data["agent_test_only"] = True
            unit = getattr(agent.task_state, "work_unit", None)
            if unit and not unit.closed:
                from pathlib import Path
                from ..editing.edit_verifier import EditVerifier
                syntax_errors = []
                for path in unit.edited_paths:
                    file = Path(agent.workspace) / path
                    if file.suffix == ".py" and file.is_file():
                        try:
                            EditVerifier.validate_candidate(file, file.read_text(encoding="utf-8"))
                        except (ValueError, OSError, UnicodeError) as exc:
                            syntax_errors.append(f"{path}: {exc}")
                if syntax_errors:
                    result.data.update(outcome="failed", tests_passed=False, command_succeeded=False,
                                       failed=len(syntax_errors), failed_tests=syntax_errors,
                                       milestone_syntax_errors=syntax_errors)
                    if capabilities & {"validation.static_web", "validation.browser", "service.validate"}:
                        result.data["errors"] = [*result.data.get("errors", []), *syntax_errors]
            evidence = agent.validation_pipeline.observe(
                tool_name=tool_name, arguments=arguments, result=result,
                capabilities=(agent.registry.capabilities_for(tool_name)
                              if tool_name in getattr(agent.registry, "_tools", {}) else frozenset()),
            )
            if evidence is not None:
                checks = agent.validation_pipeline.state.plan.checks
                contract = next((c for c in checks if c.id == evidence.check_id), None)
                if metrics is not None and checks and evidence.purpose.value == "acceptance" and (
                    contract is None or (contract.target and contract.target != evidence.target)
                ):
                    metrics.wrong_validation_target_count += 1
                evidence_items.append(evidence)
                requirements = getattr(agent, "task_requirements", None)
                if requirements is not None:
                    RequirementEvidenceResolver().resolve(requirements, agent.validation_pipeline.state)
                    agent.sync_requirements_state()
                validation_state = agent.validation_pipeline.state
                self._emit_event(
                    agent,
                    RuntimeEventType.VALIDATION_OBSERVED,
                    outcome=evidence.outcome,
                    validation_revision=getattr(validation_state, "evidence_sequence", 0),
                    acceptance_passed=validation_state.acceptance_passed,
                    relevant_validation_passed=validation_state.targeted_passed,
                    full_validation_passed=validation_state.full_passed,
                    evidence_edit_revision=evidence.edit_revision,
                    validation_check=evidence.check_id,
                    requirement_ids=evidence.requirement_ids,
                    capabilities=tuple(sorted(capabilities)),
                    workunit_id=unit.id if unit else None,
                )
                _, completed = agent.plan_orchestrator.reconcile(agent)
                print(
                    f"\n[Validation Evidence]\nRevision: {evidence.edit_revision}"
                    f"\nScope: {evidence.scope.value}\nPurpose: {evidence.purpose.value}"
                    f"\nOutcome: {evidence.outcome.value}"
                )
                decision = agent.validation_orchestrator.apply(agent=agent, evidence=evidence)
                if (
                    evidence.outcome.value == "passed"
                    and agent.task_state.recovery_level > 0
                    and metrics is not None
                ):
                    metrics.recovery_successes += 1
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
    def _is_validation(tool_name: str, arguments: dict) -> bool:
        return tool_name in {"run_tests", "validate_static_web", "validate_browser_app"} or (
            tool_name == "run_command"
            and str(arguments.get("purpose", "diagnostic")).strip().lower() in {"acceptance", "regression"}
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
