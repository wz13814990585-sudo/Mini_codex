"""Mode-aware orchestration completion policy."""

from __future__ import annotations

from dataclasses import replace

from .completion import (
    CompletionDecision,
    CompletionGate,
    CompletionStatus,
    TaskOutcome,
)
from .regression_policy import RegressionRequirement


class TaskCompletionPolicy:
    """Combine fresh validation facts, regression scope, and plan state."""

    def __init__(self, gate: CompletionGate | None = None) -> None:
        self.gate = gate or CompletionGate()

    def evaluate(self, agent) -> CompletionDecision:
        pipeline = getattr(agent, "validation_pipeline", None)
        if pipeline is None:
            return self.gate.evaluate(
                edit_revision=0,
                has_edit=False,
                acceptance_passed=False,
                full_validation_passed=False,
            )

        state = pipeline.state
        policy = getattr(agent, "execution_policy", None)
        requirement = (
            agent.current_regression_requirement()
            if hasattr(agent, "current_regression_requirement")
            else getattr(
                policy,
                "regression_requirement",
                RegressionRequirement.REQUIRED,
            )
        )
        decision = self.gate.evaluate(
            edit_revision=state.edit_revision,
            has_edit=state.has_edit,
            acceptance_passed=state.acceptance_passed,
            full_validation_passed=state.full_passed,
            relevant_validation_passed=state.targeted_passed,
            require_acceptance=getattr(policy, "require_acceptance", True),
            regression_requirement=requirement,
            allow_already_satisfied=True,
        )

        task_state = getattr(agent, "task_state", None)
        phase = getattr(task_state, "phase", None)
        if getattr(phase, "value", phase) == "blocked":
            return replace(
                decision,
                status=CompletionStatus.NOT_READY,
                outcome=TaskOutcome.BLOCKED,
                reason="The task is blocked by a concrete external or safety constraint.",
            )

        requirements = getattr(agent, "task_requirements", None)
        if (
            decision.can_complete
            and requirements is not None
            and getattr(requirements, "items", None)
            and not requirements.all_satisfied
        ):
            missing = "; ".join(item.description for item in requirements.unsatisfied[:4])
            return replace(
                decision,
                status=CompletionStatus.NOT_READY,
                outcome=TaskOutcome.INCOMPLETE,
                reason=f"Task requirements lack current evidence: {missing}",
            )

        plan = getattr(agent, "active_plan", None)
        plan_required = bool(getattr(policy, "use_plan", plan is not None))
        if decision.can_complete and plan_required and plan is None:
            return replace(
                decision,
                status=CompletionStatus.NOT_READY,
                outcome=TaskOutcome.INCOMPLETE,
                reason="The routing policy requires a plan, but no valid active plan exists.",
            )
        if (
            decision.can_complete
            and plan_required
            and plan is not None
            and not plan.is_completed()
        ):
            return replace(
                decision,
                status=CompletionStatus.NOT_READY,
                outcome=TaskOutcome.INCOMPLETE,
                reason=(
                    "Validation requirements are satisfied, but the active "
                    "outcome plan still has unfinished steps."
                ),
            )
        if decision.can_complete and task_state is not None:
            task_state.mark_finalizing()
        return decision
