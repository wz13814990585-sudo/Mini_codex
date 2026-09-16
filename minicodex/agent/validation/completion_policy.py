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

        pipeline_state = pipeline.state
        task_state = getattr(agent, "task_state", None)
        # A started TaskRuntime is authoritative. Isolated legacy callers that
        # construct only a ValidationPipeline continue to use that projection.
        state = (
            task_state
            if task_state is not None and getattr(task_state, "run_id", "")
            else pipeline_state
        )
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
            full_validation_passed=getattr(
                state, "full_validation_passed", getattr(state, "full_passed", False)
            ),
            relevant_validation_passed=getattr(
                state, "relevant_validation_passed", getattr(state, "targeted_passed", False)
            ),
            require_acceptance=getattr(policy, "require_acceptance", True),
            regression_requirement=requirement,
            allow_already_satisfied=True,
        )

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
            and (
                (
                    task_state is not None
                    and getattr(task_state, "run_id", "")
                    and set(task_state.requirement_ids)
                    != set(task_state.satisfied_requirement_ids)
                )
                or (
                    not getattr(task_state, "run_id", "")
                    and not requirements.all_satisfied
                )
            )
        ):
            missing = "; ".join(item.description for item in requirements.unsatisfied[:4])
            return replace(
                decision,
                status=CompletionStatus.NOT_READY,
                outcome=TaskOutcome.INCOMPLETE,
                reason=f"Task requirements lack current evidence: {missing}",
            )

        return decision
