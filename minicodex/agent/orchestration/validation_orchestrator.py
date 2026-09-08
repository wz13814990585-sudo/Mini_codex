"""Validation progress, recovery, rollback, and completion orchestration."""

from __future__ import annotations

import re

from .control_decision import ControlDecision
from .orchestration_transitions import (
    completion_transition,
    plan_is_incomplete,
    validation_transition,
)
from ..progress import ValidationStatus
from ..reason_codes import ReasonCode
from ..validation import ValidationEvidence, ValidationOutcome
from ..editing.rollback_coordinator import RollbackCoordinator


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
            revision=getattr(
                getattr(agent, "validation_pipeline", None), "state", None
            ).edit_revision
            if getattr(getattr(agent, "validation_pipeline", None), "state", None)
            else 0,
            desired_purpose="acceptance",
        )
        if selection is not None:
            if selection.tool_name == "validate_static_web":
                return prefix + (
                    "Obtain targeted acceptance evidence for the CURRENT edit revision "
                    f"with validate_static_web(path={selection.path!r})."
                )
            if selection.tool_name == "run_tests":
                if selection.purpose == "acceptance":
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
    def __init__(self, rollback_coordinator: RollbackCoordinator | None = None) -> None:
        self.rollback_coordinator = rollback_coordinator or RollbackCoordinator()

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
            rollback = self.rollback_coordinator.coordinate(agent, evidence, progress)
            if rollback is not None:
                return rollback

        if progress.meaningful_progress:
            agent.recovery.mark_progress()
            print("\n[Meaningful Progress Detected]")

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

_DEFAULT = ValidationOrchestrator()


def apply_validation_evidence(agent, evidence, messages=None):
    return _DEFAULT.apply(agent, evidence, messages)


def rollback_regressed_edit(*, agent, evidence, validation_progress, messages=None):
    del messages
    return _DEFAULT.rollback_coordinator.coordinate(agent, evidence, validation_progress)


def completion_result(agent, decision, last_text: str = "") -> str:
    del last_text
    handler = getattr(agent, "completion_handler", None)
    if handler is None:
        # Compatibility for narrow unit fixtures. Production agents always own
        # a CompletionHandler and therefore have a single termination owner.
        from .completion_handler import CompletionHandler

        handler = CompletionHandler()
    return handler.finish_ready(agent, decision).output or ""
