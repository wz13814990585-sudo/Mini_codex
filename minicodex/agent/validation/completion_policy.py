"""Completion is a projection of required current-revision ledger proofs."""

from __future__ import annotations

from .completion import CompletionDecision, CompletionStatus, TaskOutcome
from .plan import EvidenceStrength
from .regression_policy import RegressionRequirement


class TaskCompletionPolicy:
    def evaluate(self, agent) -> CompletionDecision:
        pipeline = getattr(agent, "validation_pipeline", None)
        if pipeline is None:
            return CompletionDecision(
                CompletionStatus.NOT_READY, 0, False, False, False,
                "验证账本不可用。",
            )
        ledger = pipeline.state
        required = ledger.required_checks
        missing = [check for check in required if ledger.proof(check.id) is None]
        blocked = [
            check for check in missing
            if check.id in ledger.blocked_checks
        ]
        if blocked:
            reason = "；".join(
                f"{check.id}: {ledger.blocked_checks[check.id]}" for check in blocked
            )
            return CompletionDecision(
                CompletionStatus.NOT_READY,
                ledger.edit_revision,
                ledger.has_edit,
                ledger.acceptance_passed,
                ledger.full_passed,
                f"必需验证能力被阻塞：{reason}",
                TaskOutcome.BLOCKED,
            )
        if missing:
            acceptance_missing = any(check.purpose.value == "acceptance" for check in missing)
            status = (
                CompletionStatus.NEEDS_ACCEPTANCE
                if acceptance_missing
                else CompletionStatus.NEEDS_RELEVANT_VALIDATION
            )
            return CompletionDecision(
                status,
                ledger.edit_revision,
                ledger.has_edit,
                ledger.acceptance_passed,
                ledger.full_passed,
                "缺少当前版本必需检查证据：" + ", ".join(check.id for check in missing),
            )
        if not required:
            return CompletionDecision(
                CompletionStatus.NOT_READY,
                ledger.edit_revision,
                ledger.has_edit,
                False,
                False,
                "尚未物化必需验证检查。",
            )

        requirements = getattr(agent, "task_requirements", None)
        allow_no_edit = bool(
            getattr(requirements, "no_edit_if_already_satisfied", True)
        )
        if not ledger.has_edit and not allow_no_edit:
            return CompletionDecision(
                CompletionStatus.NOT_READY,
                ledger.edit_revision,
                False,
                ledger.acceptance_passed,
                ledger.full_passed,
                "请求要求实施变更；初始验收通过不足以证明无需编辑。",
            )

        regression_requirement = RegressionRequirement.UNKNOWN
        resolver = getattr(agent, "current_regression_requirement", None)
        if ledger.has_edit and callable(resolver):
            regression_requirement = resolver()
        regression_checks = tuple(
            check for check in required
            if check.purpose.value == "regression"
        )
        if (
            regression_requirement == RegressionRequirement.REQUIRED
            and not any(check.strength >= EvidenceStrength.FULL for check in regression_checks)
        ):
            return CompletionDecision(
                CompletionStatus.NEEDS_FULL_VALIDATION,
                ledger.edit_revision,
                ledger.has_edit,
                ledger.acceptance_passed,
                False,
                "当前变更策略要求完整回归，但尚未物化完整回归检查。",
            )
        if (
            regression_requirement == RegressionRequirement.RELEVANT_ONLY
            and not regression_checks
        ):
            return CompletionDecision(
                CompletionStatus.NEEDS_RELEVANT_VALIDATION,
                ledger.edit_revision,
                ledger.has_edit,
                ledger.acceptance_passed,
                False,
                "当前变更策略要求相关回归，但尚未物化相关回归检查。",
            )
        return CompletionDecision(
            CompletionStatus.READY,
            ledger.edit_revision,
            ledger.has_edit,
            ledger.acceptance_passed,
            ledger.full_passed,
            "当前编辑版本的全部必需检查均已由账本证明。",
            TaskOutcome.EDITED_AND_VALIDATED if ledger.has_edit else TaskOutcome.ALREADY_SATISFIED,
        )
