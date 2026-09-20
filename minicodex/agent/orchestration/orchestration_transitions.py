"""Phase-aware validation and completion transitions for the shared loop."""

from __future__ import annotations

from dataclasses import dataclass

from ..validation import (
    CompletionDecision,
    CompletionStatus,
    TaskCompletionPolicy,
    TaskOutcome,
    ValidationNextAction,
)
from .control_decision import ControlDecision
from ..routing import ExecutionMode
from ..reason_codes import ReasonCode


@dataclass(frozen=True)
class CompletionTransition:
    decision: CompletionDecision
    plan_incomplete: bool

    @property
    def can_finish(self) -> bool:
        # A plan is an execution aid. It is never business truth and cannot
        # veto current-revision requirement and validation evidence.
        return self.decision.can_complete


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
    apply_event = getattr(agent, "apply_runtime_event", None)
    if callable(apply_event):
        from ..task_state import RuntimeEventType

        apply_event(
            RuntimeEventType.TASK_BLOCKED if outcome == TaskOutcome.BLOCKED else RuntimeEventType.TASK_COMPLETED,
            outcome=outcome,
            reason=reason,
        )


def validation_transition(
    agent,
    *,
    next_action: ValidationNextAction,
    stalled: bool,
    acceptance_reminder: str,
    next_check=None,
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
                skipped_reason="确定性完成证据已充分",
            )
        return ControlDecision()
    # A materialized plan is the production source of the next action.  Do
    # this before legacy acceptance/regression projections can generalize it.
    if next_action == ValidationNextAction.RUN_CHECK:
        check = next_check
        return ControlDecision(
            restart=True,
            followup_message=(
                f"Harness 将直接执行必需验证项 {check.id}（{check.contract_type}）。"
                "不要由模型重新选择或复制验证器参数。"
                if check is not None else "Harness 将执行下一个必需验证项。"
            ),
            skipped_reason="仍有必需验证项尚未证明",
            reason_code=ReasonCode.ACCEPTANCE_MISSING,
        )
    if (
        completion.status == CompletionStatus.NEEDS_RELEVANT_VALIDATION
        and completion.acceptance_passed
    ):
        return ControlDecision(
            restart=True,
            followup_message=(
                "验收已通过。请针对变更区域运行一次聚焦回归测试，"
                "并设置 purpose='regression'。"
            ),
            skipped_reason="仍需要相关回归证据",
            reason_code=ReasonCode.REGRESSION_MISSING,
        )
    if next_action == ValidationNextAction.RUN_ACCEPTANCE_VALIDATION:
        return ControlDecision(
            restart=True,
            followup_message=acceptance_reminder,
            skipped_reason="验证仍需要验收证据",
            reason_code=ReasonCode.ACCEPTANCE_MISSING,
        )
    if next_action == ValidationNextAction.RUN_FULL_VALIDATION:
        return ControlDecision(
            restart=True,
            followup_message=(
                "验收已通过。完成前请运行完整回归套件："
                "run_tests(path='.', purpose='regression')。"
            ),
            skipped_reason="验证仍需要完整回归证据",
            reason_code=ReasonCode.FULL_REGRESSION_MISSING,
        )
    if next_action == ValidationNextAction.INVESTIGATE_INCONCLUSIVE:
        return ControlDecision(
            restart=True,
            followup_message=(
                "验证结果尚无定论。请检查具体验证器失败信息，并获取可靠证据。"
            ),
            skipped_reason="验证结果尚无定论",
        )
    if next_action in {ValidationNextAction.TASK_VALIDATED, ValidationNextAction.FIX_FAILURE}:
        return None if stalled else ControlDecision()
    return None
