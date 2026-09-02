from agent.loop import run_agent_loop
from agent.state import AgentPlan
from agent.progress import ProgressController
from agent.recovery import RecoveryController


class MiniCodexAgent:

    def __init__(
        self,
        llm,
        registry,
        planner=None,
        replanner=None,
        max_steps: int = 20,
        max_step_attempts: int = 5,
    ):
        self.llm = llm
        self.registry = registry

        self.planner = planner
        self.replanner = replanner

        self.max_steps = max_steps
        self.max_step_attempts = max_step_attempts

        # 当前任务状态
        self.active_plan: AgentPlan | None = None
        self.active_user_request: str | None = None

        # 进度检测
        self.progress = ProgressController(
            max_same_tool_repeats=2,
            progress_window=6,
            max_validation_no_progress=2,
        )

        # 恢复控制
        self.recovery = RecoveryController(
            max_recovery_level=3
        )

    # =========================================================
    # Main Entry
    # =========================================================

    def run(
        self,
        user_input: str,
        use_planning: bool = True,
    ) -> str:

        self.active_user_request = user_input
        self.active_plan = None

        # 新任务开始时清空状态
        self.progress.reset()
        self.recovery.reset()

        # =====================================================
        # 1. Planning
        # =====================================================

        if use_planning and self.planner:
            try:
                self.active_plan = self.planner.create_plan(
                    user_input
                )

                self._print_plan(
                    self.active_plan
                )

            except Exception as e:
                print(
                    f"\n[Planning Failed] "
                    f"{type(e).__name__}: {e}"
                )

        return run_agent_loop(
            self,
            user_input,
        )

    # =========================================================
    # Complete Plan Step
    # =========================================================

    def complete_plan_step(self) -> str:

        if self.active_plan is None:
            return "No active plan."

        step = (
            self.active_plan.complete_current_step()
        )

        if step is None:
            return "No active plan step."

        self.recovery.mark_progress()

        self._print_plan(
            self.active_plan
        )

        return (
            f"Completed plan step "
            f"{step.id}: "
            f"{step.description}"
        )

    # =========================================================
    # Replan
    # =========================================================

    def replan(
        self,
        reason: str,
    ) -> str:

        if self.active_plan is None:
            return "No active plan to revise."

        if self.replanner is None:
            return "No replanner configured."

        if self.active_user_request is None:
            return "Original request unavailable."

        try:
            new_plan = self.replanner.replan(
                user_request=(
                    self.active_user_request
                ),
                current_plan=(
                    self.active_plan
                ),
                reason=reason,
            )

        except Exception as e:
            return (
                "Replanning failed: "
                f"{type(e).__name__}: {e}"
            )

        self.active_plan = new_plan

        # 新 Plan 不应该继承旧的 progress history
        self.progress.reset()

        print(
            "\n[Replanned]"
        )
        print(
            f"Reason: {reason}"
        )

        self._print_plan(
            self.active_plan
        )

        return (
            "Plan successfully revised. "
            "Continue execution using the new plan."
        )

    # =========================================================
    # Step Type Detection
    # =========================================================

    def _step_likely_requires_edit(
        self,
        current_step,
    ) -> bool:

        if current_step is None:
            return False

        text = (
            current_step.description.lower()
        )

        edit_keywords = {
            "fix",
            "modify",
            "change",
            "implement",
            "add",
            "update",
            "remove",
            "refactor",
            "修复",
            "修改",
            "实现",
            "增加",
            "添加",
            "更新",
            "删除",
            "重构",
        }

        return any(
            keyword in text
            for keyword in edit_keywords
        )

    # =========================================================
    # System Prompt
    # =========================================================

    def _build_system_prompt(
        self,
        user_input: str,
        plan,
        current_step,
    ) -> str:

        plan_text = (
            self._plan_to_text(plan)
            if plan
            else "No explicit plan."
        )

        if current_step:
            current_step_text = (
                f"{current_step.id}. "
                f"{current_step.description}"
            )
        else:
            current_step_text = (
                "No active plan step."
            )

        return f"""
You are MiniCodex, an autonomous coding agent.

User goal:
{user_input}

Implementation plan:
{plan_text}

Current plan step:
{current_step_text}

Focus primarily on completing the current plan step.

Rules:

1. Inspect relevant code before modifying it.

2. Prefer search_code when locating code.

3. Prefer patch_file for targeted edits.

4. Use write_file mainly for new files or when
   full replacement is genuinely required.

5. Validate changes after modifying code.

6. Prefer run_tests when tests exist.

7. If validation fails and enough evidence exists,
   make a targeted fix instead of repeatedly
   rerunning the same validation.

8. Do not repeat substantially identical actions
   without obtaining new information.

9. Make the smallest reasonable code change.

10. Do not change unrelated code merely to make
    tests pass.

11. Do not claim success unless tool output
    confirms success.

12. Trust real tool observations over assumptions
    in the plan.

13. When the CURRENT plan step is genuinely
    complete, call complete_plan_step.

14. If the plan itself is based on an incorrect
    assumption, call replan with a clear reason.

15. Do not replan for a single ordinary tool error
    if it can reasonably be recovered locally.

16. If recovery feedback says the current strategy
    is stalled, choose a materially different action.

17. Stop when the user's overall goal is complete.
"""

    # =========================================================
    # Plan → Text
    # =========================================================

    def _plan_to_text(
        self,
        plan: AgentPlan,
    ) -> str:

        return "\n".join(
            (
                f"{step.id}. "
                f"[{step.status.value}] "
                f"{step.description} "
                f"(attempts={step.attempts})"
            )
            for step in plan.steps
        )

    # =========================================================
    # Print Plan
    # =========================================================

    def _print_plan(
        self,
        plan: AgentPlan,
    ) -> None:

        print(
            f"\n[Plan] {plan.goal}"
        )

        for step in plan.steps:
            print(
                f"{step.id}. "
                f"[{step.status.value}] "
                f"{step.description} "
                f"(attempts={step.attempts})"
            )
