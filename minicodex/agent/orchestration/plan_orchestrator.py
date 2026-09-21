"""Own plan-step lifecycle and bounded plan recovery."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..planning.plan_quality import PlanQualityValidator
from ..planning.state import StepStatus
from ..validation.decision_policy import ValidationDecisionPolicy


_LOCATE_STEP = re.compile(
    r"定位|探查|查找构造|find (?:the )?location|locate ",
    re.IGNORECASE,
)

@dataclass(frozen=True)
class PlanTurnState:
    current_step: object | None
    can_continue: bool
    followup_message: str | None = None
    terminal_reason: str | None = None
    replanned: bool = False


class PlanOrchestrator:
    def begin_turn(self, agent) -> PlanTurnState:
        plan = getattr(agent, "active_plan", None)
        if plan is None:
            return PlanTurnState(None, True)

        current = plan.start_current_step()
        if current is None or current.attempts < agent.max_step_attempts:
            return PlanTurnState(current, True)

        # Zero-edit + pending acceptance: never let locate/process plan steps
        # terminate the task. Force an edit instead of recovery death / replan
        # into more reconnaissance milestones.
        if self._must_keep_editing(agent):
            return self._force_edit_after_step_stall(agent, plan, current)

        reason = (
            f"计划步骤 {current.id} 已超过尝试次数上限。"
            f"当前步骤：{current.description}"
        )
        previous_plan = plan
        recovery_message, should_continue = agent.recovery.recover(
            reason=reason,
            replan_callback=agent.replan,
        )
        if not should_continue:
            return PlanTurnState(
                current,
                False,
                terminal_reason=reason,
                replanned=getattr(agent, "active_plan", None) is not previous_plan,
            )

        current.reset_attempts()
        active = getattr(agent, "active_plan", None)
        next_step = active.start_current_step() if active is not None else None
        return PlanTurnState(
            next_step,
            True,
            followup_message=recovery_message,
            replanned=active is not previous_plan,
        )

    @staticmethod
    def _must_keep_editing(agent) -> bool:
        ledger = getattr(getattr(agent, "validation_pipeline", None), "state", None)
        if ledger is None:
            return False
        if int(getattr(ledger, "edit_revision", 0) or 0) > 0:
            return False
        check = ValidationDecisionPolicy(ledger).next_required_check()
        return check is not None

    @classmethod
    def _force_edit_after_step_stall(cls, agent, plan, current) -> PlanTurnState:
        description = str(getattr(current, "description", "") or "")
        if cls._is_reconnaissance_step(description):
            current.status = StepStatus.SUPERSEDED
            if current in plan.steps:
                plan.steps.remove(current)
                plan.completed_history.append(current)
            agent.plan_version += 1
            sync = getattr(agent, "sync_plan_state", None)
            if callable(sync):
                sync()
            current = plan.start_current_step()

        if current is not None:
            current.reset_attempts()

        force = ""
        controller = getattr(agent, "action_controller", None)
        if controller is not None:
            activate = getattr(controller, "_activate", None)
            if callable(activate):
                activate()
            force = str(getattr(controller, "force_edit_instruction", lambda: "")() or "")
        if not force:
            force = (
                "验收尚未通过且尚未编辑工作区。"
                "请立即用 write_file/patch_file 修改验收目标文件；"
                "不要继续定位/探查类计划步骤。"
            )
        return PlanTurnState(current, True, followup_message=force)

    @staticmethod
    def _is_reconnaissance_step(description: str) -> bool:
        text = str(description or "")
        return bool(
            PlanQualityValidator._PROCESS_ONLY.search(text)
            or PlanQualityValidator._PERMISSION_SEEKING.search(text)
            or _LOCATE_STEP.search(text)
        )

    @staticmethod
    def record_attempt_failure(current_step) -> None:
        if current_step is not None:
            current_step.increment_attempt()

    @staticmethod
    def reconcile(agent) -> tuple[object | None, tuple[int, ...]]:
        if getattr(agent, "active_plan", None) is None:
            return None, ()
        result = agent.reconcile_plan_progress()
        completed = tuple(item["step_id"] for item in result["completed"])
        return agent.active_plan.start_current_step(), completed

    def reconcile_progress(self, agent) -> dict:
        """Complete sequential plan outcomes proven by current evidence."""

        completed = []
        evaluations = []
        while agent.active_plan is not None:
            step = agent.active_plan.get_current_step()
            if step is None:
                break
            evaluation = agent.plan_progress_reconciler.evaluate_step(
                step, validation_state=agent.validation_pipeline.state
            )
            evaluations.append(
                {
                    "step_id": step.id,
                    "machine_checkable": evaluation.machine_checkable,
                    "satisfied": evaluation.satisfied,
                }
            )
            if not evaluation.satisfied:
                break
            result = self.complete_step(agent)
            if not result.get("completed"):
                break
            completed.append(
                {
                    "step_id": result["step_id"],
                    "step_description": result["step_description"],
                }
            )
        agent.sync_plan_state()
        return {"completed": completed, "evaluations": evaluations}

    @staticmethod
    def complete_step(agent) -> dict:
        plan = agent.active_plan
        if plan is None:
            return {
                "completed": False,
                "step_id": None,
                "step_description": None,
                "message": "当前没有活动计划。",
            }
        current = plan.get_current_step()
        if current is not None and agent.execution_policy is not None:
            criteria = list(current.acceptance_criteria or [])
            if criteria:
                evaluation = agent.plan_progress_reconciler.evaluate_step(
                    current, validation_state=agent.validation_pipeline.state
                )
                if not evaluation.satisfied:
                    return PlanOrchestrator._completion_rejected(
                        current,
                        "plan_step_criteria_not_satisfied",
                        "当前计划步骤仍有未满足的可机器检查条件。",
                    )
            elif getattr(current, "requires_semantic_completion", False) and not agent.step_evidence.has_validation(
                step_id=current.id,
                edit_revision=agent.validation_pipeline.state.edit_revision,
            ):
                return PlanOrchestrator._completion_rejected(
                    current,
                    "broad_semantic_step_without_acceptance_evidence",
                    "宽泛语义步骤需要当前版本的验收证据。",
                )
            elif not agent.step_evidence.has_sufficient(
                step_id=current.id,
                edit_revision=agent.validation_pipeline.state.edit_revision,
            ):
                return PlanOrchestrator._completion_rejected(
                    current,
                    "semantic_step_completion_without_fresh_evidence",
                    "语义完成需要充分的当前版本证据。",
                )
        step = plan.complete_current_step()
        if step is None:
            return {
                "completed": False,
                "step_id": None,
                "step_description": None,
                "message": "当前没有活动计划步骤。",
            }
        agent.recovery.mark_progress()
        agent.progress.reset()
        agent.plan_version += 1
        agent.sync_plan_state()
        agent._print_plan(plan)
        return {
            "completed": True,
            "step_id": step.id,
            "step_description": step.description,
            "message": f"已完成计划步骤 {step.id}：{step.description}",
        }

    @staticmethod
    def _completion_rejected(step, failure_type: str, message: str) -> dict:
        return {
            "completed": False,
            "step_id": step.id,
            "step_description": step.description,
            "failure_type": failure_type,
            "message": message,
        }

    @staticmethod
    def replan_task(agent, reason: str) -> dict:
        if agent.active_plan is None:
            return PlanOrchestrator._replan_failure(reason, "没有可修订的活动计划。")
        policy = agent.execution_policy
        if policy is not None and not policy.enable_replan:
            return PlanOrchestrator._replan_failure(
                reason, "执行策略已禁用重新规划。"
            )
        if policy is not None and agent.replan_count >= policy.max_replans:
            return PlanOrchestrator._replan_failure(reason, "重新规划预算已用尽。")
        if agent.replanner is None:
            return PlanOrchestrator._replan_failure(reason, "未配置重新规划器。")
        if agent.active_user_request is None:
            return PlanOrchestrator._replan_failure(reason, "原始请求不可用。")
        try:
            new_plan = agent.replanner.replan(
                user_request=agent.active_user_request,
                current_plan=agent.active_plan,
                reason=reason,
                token_metrics=agent.token_metrics,
            )
        except Exception as exc:
            return PlanOrchestrator._replan_failure(
                reason, f"重新规划失败：{type(exc).__name__}: {exc}"
            )
        agent.active_plan = new_plan
        agent.replan_count += 1
        agent.plan_version += 1
        agent.progress.reset()
        agent.sync_plan_state()
        print("\n[已重新规划]")
        print(f"原因：{reason}")
        agent._print_plan(new_plan)
        return {
            "replanned": True,
            "reason": reason,
            "failure_reason": None,
            "message": "计划已成功修订。请按新计划继续。",
        }

    @staticmethod
    def _replan_failure(reason: str, message: str) -> dict:
        return {
            "replanned": False,
            "reason": reason,
            "failure_reason": message,
            "message": message,
        }
