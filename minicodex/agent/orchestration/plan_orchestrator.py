"""Own plan-step lifecycle and bounded plan recovery."""

from __future__ import annotations

from dataclasses import dataclass


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

        reason = (
            f"Plan step {current.id} has exceeded its attempt budget. "
            f"Current step: {current.description}"
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
                "message": "No active plan.",
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
                        "The current plan step has unsatisfied machine-checkable criteria.",
                    )
            elif getattr(current, "requires_semantic_completion", False) and not agent.step_evidence.has_validation(
                step_id=current.id,
                edit_revision=agent.validation_pipeline.state.edit_revision,
            ):
                return PlanOrchestrator._completion_rejected(
                    current,
                    "broad_semantic_step_without_acceptance_evidence",
                    "A broad semantic step requires current-revision acceptance evidence.",
                )
            elif not agent.step_evidence.has_sufficient(
                step_id=current.id,
                edit_revision=agent.validation_pipeline.state.edit_revision,
            ):
                return PlanOrchestrator._completion_rejected(
                    current,
                    "semantic_step_completion_without_fresh_evidence",
                    "Semantic completion requires sufficient current-revision evidence.",
                )
        step = plan.complete_current_step()
        if step is None:
            return {
                "completed": False,
                "step_id": None,
                "step_description": None,
                "message": "No active plan step.",
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
            "message": f"Completed plan step {step.id}: {step.description}",
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
            return PlanOrchestrator._replan_failure(reason, "No active plan to revise.")
        policy = agent.execution_policy
        if policy is not None and not policy.enable_replan:
            return PlanOrchestrator._replan_failure(
                reason, "Replanning is disabled by execution policy."
            )
        if policy is not None and agent.replan_count >= policy.max_replans:
            return PlanOrchestrator._replan_failure(reason, "Replan budget exhausted.")
        if agent.replanner is None:
            return PlanOrchestrator._replan_failure(reason, "No replanner configured.")
        if agent.active_user_request is None:
            return PlanOrchestrator._replan_failure(reason, "Original request unavailable.")
        try:
            new_plan = agent.replanner.replan(
                user_request=agent.active_user_request,
                current_plan=agent.active_plan,
                reason=reason,
                token_metrics=agent.token_metrics,
            )
        except Exception as exc:
            return PlanOrchestrator._replan_failure(
                reason, f"Replanning failed: {type(exc).__name__}: {exc}"
            )
        agent.active_plan = new_plan
        agent.replan_count += 1
        agent.plan_version += 1
        agent.progress.reset()
        agent.sync_plan_state()
        print("\n[Replanned]")
        print(f"Reason: {reason}")
        agent._print_plan(new_plan)
        return {
            "replanned": True,
            "reason": reason,
            "failure_reason": None,
            "message": "Plan successfully revised. Continue with the new plan.",
        }

    @staticmethod
    def _replan_failure(reason: str, message: str) -> dict:
        return {
            "replanned": False,
            "reason": reason,
            "failure_reason": message,
            "message": message,
        }
