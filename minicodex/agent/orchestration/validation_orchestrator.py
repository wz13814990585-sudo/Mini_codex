"""Validation progress, recovery, rollback, and completion orchestration."""

from __future__ import annotations
from ..validation.decision_policy import ValidationDecisionPolicy

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
from ..validation import RegressionClassification
from ..editing.rollback_coordinator import RollbackCoordinator


def validation_evidence_key(evidence: ValidationEvidence) -> str:
    return evidence.validation_key


def active_plan_incomplete(agent) -> bool:
    return plan_is_incomplete(agent)


def evaluate_completion(agent):
    return completion_transition(agent).decision


def can_complete_edit_task(agent) -> bool:
    return evaluate_completion(agent).can_complete


def can_finish_edit_task(agent) -> bool:
    return evaluate_completion(agent).can_complete


def acceptance_evidence_reminder(
    agent,
    *,
    prefix: str = (
        "仅靠回归验证不足以证明用户请求的行为已经生效。"
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

    resolver = getattr(agent, "validator_resolver", None)
    ledger = getattr(getattr(agent, "validation_pipeline", None), "state", None)
    if resolver is not None and ledger is not None:
        check = next((c for c in ledger.plan.checks if c.required and not ledger.proof(c.id)
                      and c.purpose.value == "acceptance"), None)
        selection = resolver.resolve(check, registry=registry,
                                     profile=getattr(getattr(agent, "workspace_session", None), "profile", None),
                                     paths=tuple(dict.fromkeys(candidates)),
                                     revision=getattr(getattr(agent, "workspace_session", None), "revision", 0)) if check else None
        if selection is not None:
            return prefix + f"请运行 {selection.tool_name}，参数为 {selection.arguments!r}；它对应 {check.id}。"

    html = next((path for path in candidates if path.lower().endswith(".html")), None)
    if html and "validate_static_web" in registered:
        return prefix + (
            "请为当前编辑版本获取定向验收证据："
            f"validate_static_web(path={html!r})。"
        )
    if "run_command" in registered:
        return prefix + (
            "请使用 run_command(command=<验收命令>, purpose='acceptance') "
            "运行能证明具体行为的命令。"
        )
    if "run_tests" in registered:
        return prefix + (
            "请创建或定位具体相关测试，然后使用 "
            "run_tests(path=<具体测试>, purpose='acceptance')；"
            "切勿把源码模块或完整套件当作验收证据。"
        )
    return prefix + "请为当前编辑版本获取明确的定向验收证据。"


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
        if evidence.unstable:
            ledger = agent.validation_pipeline.state
            attempts = sum(e.edit_revision == evidence.edit_revision and e.validation_key == evidence.validation_key
                           for e in ledger.evidence_history)
            metrics = getattr(agent, "execution_metrics", None)
            if metrics is not None:
                metrics.flaky_reruns += 1
                metrics.premature_rollbacks_prevented += 1
            if attempts >= 6:
                return ControlDecision(early_stop="有界复核后验证仍不稳定；无法据此得出回归结论。")
            return ControlDecision(restart=True,
                followup_message="同一版本的矛盾证据不稳定。请在修复或回滚前用相同检查再跑一次。",
                skipped_reason="有界不稳定复核")
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
            failure_ids=evidence.failure_ids,
            unstable=evidence.unstable,
        )
        agent.latest_progress_signal = progress.signal
        if progress.message:
            print("\n[验证进展]")
            print(progress.message)

        if (
            evidence.outcome == ValidationOutcome.FAILED
            and progress.status == ValidationStatus.REGRESSED
            and progress.crossed_revision
        ):
            if evidence.unstable:
                metrics = getattr(agent, "execution_metrics", None)
                if metrics is not None:
                    metrics.flaky_reruns += 1
                    metrics.premature_rollbacks_prevented += 1
                return ControlDecision(
                    restart=True,
                    followup_message=(
                        "可比较验证在同一版本上自相矛盾。"
                        "请先再跑一次以确认稳定性；此时不要修复或回滚。"
                    ),
                    skipped_reason="疑似不稳定验证",
                )

            judge = getattr(agent, "semantic_judge", None)
            context_builder = getattr(agent, "judge_context_builder", None)
            control = getattr(agent, "runtime_control", None)
            can_judge = control is None or control.consume_control_call()
            assessment = (
                judge.assess(context_builder.build(agent, evidence, progress))
                if judge is not None and context_builder is not None and can_judge
                else None
            )
            metrics = getattr(agent, "execution_metrics", None)
            if metrics is not None and judge is not None and can_judge:
                metrics.record_semantic_judge(judge.last_telemetry)
                metrics.premature_rollbacks_prevented += 1

            classification = getattr(assessment, "classification", RegressionClassification.UNCERTAIN)
            if classification == RegressionClassification.EXPECTED_CHANGE:
                return ControlDecision(
                    restart=True,
                    followup_message=(
                        "回归证据与明确要求的契约变更一致。"
                        "请保留实现，仅更新合法受影响的测试并保持其验证强度，"
                        "然后重新运行验收/回归。"
                    ),
                    skipped_reason="语义评判判定为预期变更",
                )
            if classification == RegressionClassification.UNCERTAIN:
                return ControlDecision(
                    restart=True,
                    followup_message=(
                        "回归含义尚不确定。请检查变更行为与聚焦失败证据；"
                        "在建立因果关系之前不要回滚。"
                    ),
                    skipped_reason="语义回归评估尚不确定",
                )

            repair_policy = getattr(agent, "regression_recovery_policy", None)
            if repair_policy is not None:
                repair_policy.record_strategy(
                    f"revision:{evidence.edit_revision}|failures:{','.join(evidence.failure_ids)}"
                )
                if metrics is not None:
                    metrics.repair_attempts = repair_policy.repair_attempts
                if not repair_policy.rollback_allowed:
                    return ControlDecision(
                        restart=True,
                        followup_message=(
                            "已有真实回归证据。请做一次有界且实质不同的纠正编辑，"
                            "并用同一可比较验证再跑一遍。"
                        ),
                        skipped_reason="有界修复优先于回滚",
                    )
            rollback = self.rollback_coordinator.coordinate(agent, evidence, progress)
            if rollback is not None:
                return rollback

        if progress.meaningful_progress:
            agent.recovery.mark_progress()
            print("\n[检测到有意义进展]")

        decision_policy = ValidationDecisionPolicy(agent.validation_pipeline.state)
        next_action = decision_policy.next_action(evidence)
        print("\n[验证策略]")
        print(f"下一步：{next_action.value}")
        ordinary = validation_transition(
            agent,
            next_action=next_action,
            stalled=progress.stalled,
            acceptance_reminder=acceptance_evidence_reminder(agent),
            next_check=decision_policy.next_required_check(),
        )
        if ordinary is not None:
            return ordinary

        reason = f"验证反复失败且无明显改善。{progress.message}"
        policy = getattr(agent, "execution_policy", None)
        if policy is not None and not policy.enable_heavy_recovery:
            return ControlDecision(
                early_stop="FAST 模式已停止：定向验证持续停滞。",
                reason_code=ReasonCode.BLOCKED,
            )
        recovery_message, should_continue = agent.recovery.recover(
            reason=reason,
            replan_callback=agent.replan,
        )
        print("\n[验证恢复]")
        print(recovery_message)
        if not should_continue:
            return ControlDecision(
                early_stop="智能体已停止：验证持续停滞。",
                reason_code=ReasonCode.BLOCKED,
            )
        return ControlDecision(
            restart=True,
            followup_message=recovery_message,
            skipped_reason="验证恢复已重启循环",
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
