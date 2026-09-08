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
