"""Phase-aware validation and completion transitions for the shared loop."""

from __future__ import annotations

from dataclasses import dataclass

from ..completion import CompletionDecision, CompletionStatus, TaskOutcome
from ..completion_policy import TaskCompletionPolicy
from .control_decision import ControlDecision
from ..execution_mode import ExecutionMode
from ..validation import ValidationNextAction
from ..reason_codes import ReasonCode


@dataclass(frozen=True)
class CompletionTransition:
    decision: CompletionDecision
    plan_incomplete: bool

    @property
    def can_finish(self) -> bool:
        return self.decision.can_complete and not self.plan_incomplete


def plan_is_incomplete(agent) -> bool:
    policy = getattr(agent, "execution_policy", None)
    if getattr(policy, "mode", None) == ExecutionMode.FAST:
        return False
    plan = getattr(agent, "active_plan", None)
    return bool(plan and not plan.is_completed())


def completion_transition(agent) -> CompletionTransition:
    policy = getattr(agent, "completion_policy", None) or TaskCompletionPolicy()
    return CompletionTransition(
        decision=policy.evaluate(agent),
        plan_incomplete=plan_is_incomplete(agent),
    )


def record_task_outcome(
    agent, outcome: TaskOutcome, reason: str, reason_code: ReasonCode | None = None
) -> None:
    """Keep the central state and exported metrics consistent on every exit."""

    metrics = getattr(agent, "execution_metrics", None)
    if metrics is not None:
        metrics.finish(outcome.value, reason, reason_code)
    state = getattr(agent, "task_state", None)
    if state is not None:
        state.finish(outcome)


def validation_transition(
    agent,
    *,
    next_action: ValidationNextAction,
    stalled: bool,
    acceptance_reminder: str,
) -> ControlDecision | None:
    """Map normalized validation state to the next orchestration action.

    Regression comparison, rollback, and recovery escalation stay with their
    focused owners.  This function owns only the ordinary phase transition.
    """

    transition = completion_transition(agent)
    completion = transition.decision
    mode = getattr(getattr(agent, "execution_policy", None), "mode", None)
    if completion.can_complete:
        if mode == ExecutionMode.FAST:
            return ControlDecision(
                restart=False,
                skipped_reason="deterministic completion evidence is sufficient",
            )
        return ControlDecision()
    if (
        completion.status == CompletionStatus.NEEDS_RELEVANT_VALIDATION
        and completion.acceptance_passed
    ):
        return ControlDecision(
            restart=True,
            followup_message=(
                "Acceptance passed. Run one focused regression test for the "
                "changed area with purpose='regression'."
            ),
            skipped_reason="relevant regression evidence is required",
            reason_code=ReasonCode.REGRESSION_MISSING,
        )
    if next_action == ValidationNextAction.RUN_ACCEPTANCE_VALIDATION:
        return ControlDecision(
            restart=True,
            followup_message=acceptance_reminder,
            skipped_reason="validation requires acceptance evidence",
            reason_code=ReasonCode.ACCEPTANCE_MISSING,
        )
    if next_action == ValidationNextAction.RUN_FULL_VALIDATION:
        return ControlDecision(
            restart=True,
            followup_message=(
                "Acceptance passed. Run the full regression suite with "
                "run_tests(path='.', "
                "purpose='regression') before completion."
            ),
            skipped_reason="validation requires full regression evidence",
            reason_code=ReasonCode.FULL_REGRESSION_MISSING,
        )
    if next_action == ValidationNextAction.INVESTIGATE_INCONCLUSIVE:
        return ControlDecision(
            restart=True,
            followup_message=(
                "Validation was inconclusive. Inspect the concrete validator "
                "failure and obtain reliable evidence."
            ),
            skipped_reason="validation was inconclusive",
        )
    if next_action in {ValidationNextAction.TASK_VALIDATED, ValidationNextAction.FIX_FAILURE}:
        return None if stalled else ControlDecision()
    return None
