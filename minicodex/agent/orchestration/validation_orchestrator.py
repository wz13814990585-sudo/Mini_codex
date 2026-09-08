"""Validation progress, recovery, rollback, and completion orchestration."""

from __future__ import annotations

import re

from ..completion import CompletionStatus
from .control_decision import ControlDecision
from ..execution_mode import ExecutionMode
from .orchestration_transitions import (
    completion_transition,
    plan_is_incomplete,
    record_task_outcome,
    validation_transition,
)
from ..progress import ProgressKind, ProgressSignal, ValidationStatus
from ..reason_codes import ReasonCode
from ..validation import ValidationEvidence, ValidationOutcome


def validation_evidence_key(evidence: ValidationEvidence) -> str:
    return "|".join(
        (
            evidence.tool_name,
            evidence.purpose.value,
            evidence.scope.value,
            evidence.path or "",
        )
    )


def active_plan_incomplete(agent) -> bool:
    return plan_is_incomplete(agent)


def evaluate_completion(agent):
    return completion_transition(agent).decision


def can_complete_edit_task(agent) -> bool:
    return evaluate_completion(agent).can_complete


def can_finish_edit_task(agent) -> bool:
    return not active_plan_incomplete(agent) and evaluate_completion(agent).can_complete


def acceptance_evidence_reminder(
    agent,
    *,
    prefix: str = (
        "Regression validation is not enough to prove that the user's requested "
        "behavior works. "
    ),
) -> str:
    registry = getattr(agent, "registry", None)
    registered = set(getattr(registry, "_tools", {}) or {})
    candidates: list[str] = []
    awareness = getattr(agent, "git_awareness", None)
    if awareness is not None:
        try:
            candidates.extend(awareness.task_state().agent_touched_files)
        except Exception:
            pass
    route = getattr(agent, "execution_route", None)
    candidates.extend(getattr(route, "target_paths", ()) or ())
    plan = getattr(agent, "active_plan", None)
    if plan is not None:
        for step in plan.all_steps():
            candidates.extend(
                str(item.get("path", "")).strip()
                for item in (getattr(step, "acceptance_criteria", ()) or ())
                if item.get("path")
            )
    request = str(getattr(agent, "active_user_request", "") or "")
    candidates.extend(re.findall(r"[\w./\\-]+\.html\b", request, re.IGNORECASE))

    selector = getattr(agent, "validation_selector", None)
    if selector is not None:
        selection = selector.select(
            target_paths=tuple(dict.fromkeys(candidates)),
            registered_tools=registered,
        )
        if selection is not None:
            if selection.tool_name == "validate_static_web":
                return prefix + (
                    "Obtain targeted acceptance evidence for the CURRENT edit revision "
                    f"with validate_static_web(path={selection.path!r})."
                )
            if selection.tool_name == "run_tests":
                return prefix + (
                    "Run the resolved focused acceptance test with "
                    f"run_tests(path={selection.path!r}, purpose='acceptance')."
                )

    html = next((path for path in candidates if path.lower().endswith(".html")), None)
    if html and "validate_static_web" in registered:
        return prefix + (
            "Obtain targeted acceptance evidence for the CURRENT edit revision "
            f"with validate_static_web(path={html!r})."
        )
    if "run_command" in registered:
        return prefix + (
            "Run a specific behavior command using "
            "run_command(command=<acceptance_command>, purpose='acceptance')."
        )
    if "run_tests" in registered:
        return prefix + (
            "Create or resolve a specific relevant test, then use "
            "run_tests(path=<specific_test>, purpose='acceptance'); never pass a "
            "source module or the full suite as acceptance evidence."
        )
    return prefix + "Obtain explicit targeted acceptance evidence for the current edit revision."


class ValidationOrchestrator:
    def apply(
        self,
        agent,
        evidence: ValidationEvidence,
        messages: list | None = None,
    ) -> ControlDecision:
        del messages
        failed_count = (
            0
            if evidence.outcome == ValidationOutcome.PASSED
            else evidence.failed_count
            if evidence.outcome == ValidationOutcome.FAILED
            else None
        )
        progress = agent.progress.track_validation(
            failed_count,
            validation_key=validation_evidence_key(evidence),
            edit_revision=evidence.edit_revision,
            outcome=evidence.outcome.value,
            purpose=evidence.purpose.value,
            scope=evidence.scope.value,
            path=evidence.path or "",
        )
        agent.latest_progress_signal = progress.signal
        if progress.message:
            print("\n[Validation Progress]")
            print(progress.message)

        if (
            evidence.outcome == ValidationOutcome.FAILED
            and progress.status == ValidationStatus.REGRESSED
            and progress.crossed_revision
        ):
            rollback = self.rollback_regressed_edit(agent, evidence, progress)
            if rollback is not None:
                return rollback

        if progress.meaningful_progress:
            agent.recovery.mark_progress()
            print("\n[Meaningful Progress Detected]")

        completion = evaluate_completion(agent)
        if completion.can_complete:
            print("\n[Completion Gate]")
            print(f"Status: {completion.status.value}")
            if getattr(getattr(agent, "execution_policy", None), "mode", None) == ExecutionMode.FAST:
                return ControlDecision(
                    early_stop=completion_result(agent, completion),
                    skipped_reason="deterministic completion evidence is sufficient",
                )
            return ControlDecision()

        if completion.status == CompletionStatus.NEEDS_RELEVANT_VALIDATION and completion.acceptance_passed:
            return ControlDecision(
                restart=True,
                followup_message=(
                    "Acceptance validation passed for the current edit revision. Run "
                    "focused regression tests for the changed area with purpose='regression'."
                ),
                skipped_reason="relevant regression evidence is required",
                reason_code=ReasonCode.REGRESSION_MISSING,
            )

        next_action = agent.validation_pipeline.next_action(evidence)
        print("\n[Validation Policy]")
        print(f"Next action: {next_action.value}")
        ordinary = validation_transition(
            agent,
            next_action=next_action,
            stalled=progress.stalled,
            acceptance_reminder=acceptance_evidence_reminder(agent),
        )
        if ordinary is not None:
            return ordinary

        reason = f"Validation is repeatedly failing without meaningful improvement. {progress.message}"
        policy = getattr(agent, "execution_policy", None)
        if policy is not None and not policy.enable_heavy_recovery:
            return ControlDecision(
                early_stop="FAST mode stopped because targeted validation remained stalled.",
                reason_code=ReasonCode.BLOCKED,
            )
        recovery_message, should_continue = agent.recovery.recover(
            reason=reason,
            replan_callback=agent.replan,
        )
        print("\n[Validation Recovery]")
        print(recovery_message)
        if not should_continue:
            return ControlDecision(
                early_stop="Agent stopped because validation remained stalled.",
                reason_code=ReasonCode.BLOCKED,
            )
        return ControlDecision(
            restart=True,
            followup_message=recovery_message,
            skipped_reason="validation recovery restarted the loop",
        )

    def rollback_regressed_edit(self, agent, evidence, validation_progress):
        pipeline = getattr(agent, "validation_pipeline", None)
        manager = getattr(agent, "checkpoint_manager", None)
        engine = getattr(agent, "rollback_engine", None)
        if pipeline is None or manager is None or engine is None or not validation_progress.crossed_revision:
            return None
        current_revision = pipeline.state.edit_revision
        if evidence.edit_revision != current_revision or validation_progress.current_revision != current_revision:
            return None
        checkpoint = manager.latest_for_revision(evidence.edit_revision)
        if checkpoint is None or not checkpoint.sealed or checkpoint.rolled_back:
            return None

        print("\n[Automatic Rollback]")
        print(
            f"Validation regression detected: {validation_progress.previous_failed} "
            f"failed -> {validation_progress.current_failed} failed."
        )
        result = engine.rollback(checkpoint.checkpoint_id)
        summary = getattr(agent, "working_summary", None)
        if summary is not None:
            summary.record_tool_result(
                tool_name="automatic_rollback",
                arguments={
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "edit_revision": evidence.edit_revision,
                    "validation_key": validation_progress.validation_key,
                    "failed_before": validation_progress.previous_failed,
                    "failed_after": validation_progress.current_failed,
                },
                result=result,
            )
        if not result.success:
            return ControlDecision(
                restart=True,
                followup_message=(
                    "Validation regressed and automatic rollback failed. "
                    f"{result.to_llm_text()} Inspect the physical workspace before editing."
                ),
                skipped_reason="automatic rollback failed",
                reason_code=ReasonCode.BLOCKED,
            )

        rollback_revision = pipeline.record_edit()
        metrics = getattr(agent, "execution_metrics", None)
        if metrics is not None:
            metrics.record_rollback()
        if hasattr(agent, "rollback_revision"):
            agent.rollback_revision += 1
        agent.progress.reset()
        agent.recovery.mark_progress()
        controller = getattr(agent, "action_controller", None)
        if controller is not None:
            controller.observe_action(
                "automatic_rollback",
                agent.task_progress_state(),
                ProgressSignal(ProgressKind.OBSERVATION, "Rollback is not positive advancement."),
            )
        print("\n[Rollback Successful]")
        print(f"Restored checkpoint: {checkpoint.checkpoint_id}")
        return ControlDecision(
            restart=True,
            followup_message=(
                "The Harness automatically rolled back the regressed edit. "
                f"Checkpoint {checkpoint.checkpoint_id} was restored at revision "
                f"{rollback_revision}. Previous validation is stale; choose a materially "
                "different repair."
            ),
            skipped_reason="automatic rollback changed the workspace revision",
        )


_DEFAULT = ValidationOrchestrator()


def apply_validation_evidence(agent, evidence, messages=None):
    return _DEFAULT.apply(agent, evidence, messages)


def rollback_regressed_edit(*, agent, evidence, validation_progress, messages=None):
    del messages
    return _DEFAULT.rollback_regressed_edit(agent, evidence, validation_progress)


def completion_result(agent, decision, last_text: str = "") -> str:
    del last_text
    record_task_outcome(agent, decision.outcome, decision.reason)
    handler = getattr(agent, "completion_handler", None)
    if handler is not None:
        return handler.build_task_report(agent, outcome=decision.outcome, reason=decision.reason)
    return f"Task completed.\n\nOutcome:\n{decision.outcome.name} ({decision.outcome.value})"
