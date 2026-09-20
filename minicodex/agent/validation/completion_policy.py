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
from .plan import ValidationPlan


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

        task_state = getattr(agent, "task_state", None)
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
        ledger = pipeline.state
        validation_plan = getattr(ledger, "plan", ValidationPlan())
        if validation_plan.checks:
            required_regression = [c for c in validation_plan.checks
                                   if c.required and c.purpose.value == "regression"]
            requirement = (
                RegressionRequirement.REQUIRED
                if any(c.strength.value >= 6 for c in required_regression)
                else RegressionRequirement.RELEVANT_ONLY
                if required_regression
                else RegressionRequirement.NOT_APPLICABLE
            )
        acceptance = ledger.acceptance_passed
        if validation_plan.checks:
            acceptance_checks = [c for c in validation_plan.checks if c.required and c.purpose.value == "acceptance"]
            acceptance = bool(acceptance_checks) and all(ledger.proof(c.id) for c in acceptance_checks)
        decision = self.gate.evaluate(
            edit_revision=ledger.edit_revision,
            has_edit=ledger.has_edit,
            acceptance_passed=acceptance,
            full_validation_passed=ledger.full_passed,
            relevant_validation_passed=ledger.targeted_passed,
            require_acceptance=getattr(policy, "require_acceptance", True),
            regression_requirement=requirement,
            allow_already_satisfied=True,
        )

        phase = getattr(task_state, "phase", None)
        if getattr(task_state, "edit_issues", ()):
            return replace(decision, status=CompletionStatus.NOT_READY, outcome=TaskOutcome.INCOMPLETE,
                           reason=f"编辑后验证仍未解决：{task_state.edit_issues}")
        if decision.can_complete and validation_plan.checks:
            missing_checks = [c.id for c in validation_plan.checks if c.required and not ledger.proof(c.id)]
            if missing_checks:
                return replace(decision, status=CompletionStatus.NOT_READY, outcome=TaskOutcome.INCOMPLETE,
                               reason="缺少当前需求证据：" + ", ".join(missing_checks))
        if getattr(phase, "value", phase) == "blocked":
            return replace(
                decision,
                status=CompletionStatus.NOT_READY,
                outcome=TaskOutcome.BLOCKED,
                reason="任务被具体的外部或安全约束阻塞。",
            )

        requirements = getattr(agent, "task_requirements", None)
        if decision.can_complete and requirements is not None and validation_plan.checks:
            missing_requirements = [r.id for r in requirements.items
                                    if not validation_plan.for_requirement(r.id)]
            if missing_requirements:
                return replace(decision, status=CompletionStatus.NOT_READY, outcome=TaskOutcome.INCOMPLETE,
                               reason="需求缺少验证契约：" + ", ".join(missing_requirements))
            return decision
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
                reason=f"任务需求缺少当前证据：{missing}",
            )

        return decision
