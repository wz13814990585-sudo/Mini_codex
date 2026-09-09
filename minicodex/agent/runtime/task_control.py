"""Bounded monotonic changes to task execution scope."""

from dataclasses import dataclass
from dataclasses import replace

from ..routing import ExecutionMode, policy_for

_NEXT_MODE = {ExecutionMode.FAST: ExecutionMode.STANDARD, ExecutionMode.STANDARD: ExecutionMode.COMPLEX}


@dataclass
class RuntimeTaskControl:
    mode_escalations: int = 0
    late_plan_activations: int = 0
    planning_activated: bool = False
    control_llm_calls: int = 0
    max_control_llm_calls_per_task: int = 5

    def reset(self, *, planning_active: bool = False) -> None:
        self.mode_escalations = 0
        self.late_plan_activations = 0
        self.planning_activated = bool(planning_active)
        self.control_llm_calls = 0

    def consume_control_call(self) -> bool:
        if self.control_llm_calls >= self.max_control_llm_calls_per_task:
            return False
        self.control_llm_calls += 1
        return True

    def escalate(self, agent, *, reason: str) -> bool:
        current = agent.execution_policy.mode
        target = _NEXT_MODE.get(current)
        if target is None or self.mode_escalations >= 2:
            return False
        needs_plan = (
            bool(getattr(agent.execution_route, "needs_plan", False))
            or target == ExecutionMode.COMPLEX
            or "multiple changed files" in reason
        )
        agent.execution_policy = policy_for(target, needs_plan=needs_plan)
        agent.task_max_steps = min(agent.configured_max_steps, agent.execution_policy.max_steps)
        agent.task_state.mode = target
        self.mode_escalations += 1
        agent.execution_metrics.mode_escalations = self.mode_escalations
        agent.working_summary.add(f"Mode escalated {current.value}->{target.value}: {reason}")
        return True

    def should_escalate(self, agent, *, remaining_steps: int) -> str | None:
        try:
            changed = len(agent.git_awareness.task_state().agent_touched_files)
        except Exception:
            changed = 0
        policy = getattr(agent, "execution_policy", None)
        if policy is None:
            return None
        mode = policy.mode
        if mode == ExecutionMode.FAST and changed >= 3:
            return "runtime work expanded to multiple changed files"
        if remaining_steps <= 2 and mode != ExecutionMode.COMPLEX and not agent.validation_pipeline.state.acceptance_passed:
            return "current policy is near its total step ceiling without acceptance"
        return None

    def should_activate_plan(self, agent) -> str | None:
        if self.planning_activated or getattr(agent, "active_plan", None) is not None:
            return None
        try:
            changed = len(agent.git_awareness.task_state().agent_touched_files)
        except Exception:
            changed = 0
        if changed >= 3:
            return "runtime evidence revealed coordinated multi-file work"
        return None

    def enable_planning(self, agent) -> None:
        policy = agent.execution_policy
        if not policy.use_plan:
            agent.execution_policy = replace(
                policy,
                use_plan=True,
                max_plan_steps=max(3, policy.max_plan_steps),
                enable_replan=True,
                max_replans=max(1, policy.max_replans),
            )
