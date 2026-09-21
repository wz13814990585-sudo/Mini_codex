"""Bounded monotonic changes to task execution scope."""

from dataclasses import dataclass
from dataclasses import replace

from ..routing import ExecutionMode, policy_for
from ..task_state import RuntimeEventType

_NEXT_MODE = {ExecutionMode.FAST: ExecutionMode.STANDARD, ExecutionMode.STANDARD: ExecutionMode.COMPLEX}

# Stable machine reason codes (not user-facing display text).
REASON_MULTIPLE_CHANGED_FILES = "multiple_changed_files"
REASON_NEAR_STEP_CEILING = "near_step_ceiling_without_acceptance"
REASON_MULTI_FILE_COORDINATION = "coordinated_multi_file_work"


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
            or reason == REASON_MULTIPLE_CHANGED_FILES
            or "multiple changed files" in reason  # legacy English reasons
        )
        agent.execution_policy = policy_for(target, needs_plan=needs_plan)
        agent.task_max_steps = min(agent.configured_max_steps, agent.execution_policy.max_steps)
        agent.apply_runtime_event(RuntimeEventType.MODE_ESCALATED, mode=target)
        self.mode_escalations += 1
        agent.execution_metrics.mode_escalations = self.mode_escalations
        display = {
            REASON_MULTIPLE_CHANGED_FILES: "运行时工作已扩展到多个变更文件",
            REASON_NEAR_STEP_CEILING: "当前策略接近总步数上限且尚未通过验收",
            REASON_MULTI_FILE_COORDINATION: "运行时证据表明存在需协调的多文件工作",
        }.get(reason, reason)
        agent.working_summary.add(
            f"执行模式已升级 {current.value}->{target.value}：{display}"
        )
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
            return REASON_MULTIPLE_CHANGED_FILES
        if remaining_steps <= 2 and mode != ExecutionMode.COMPLEX and not agent.validation_pipeline.state.acceptance_passed:
            return REASON_NEAR_STEP_CEILING
        return None

    def should_activate_plan(self, agent) -> str | None:
        if self.planning_activated or getattr(agent, "active_plan", None) is not None:
            return None
        try:
            changed = len(agent.git_awareness.task_state().agent_touched_files)
        except Exception:
            changed = 0
        if changed >= 3:
            return REASON_MULTI_FILE_COORDINATION
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
