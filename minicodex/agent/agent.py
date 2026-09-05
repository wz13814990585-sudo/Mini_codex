import re

from .loop import run_agent_loop
from .state import AgentPlan
from .progress import ProgressController
from .recovery import RecoveryController
from .tool_executor import ToolExecutor
from .metrics import TokenMetrics
from .context_budget import ContextBudget
from .working_summary import WorkingSummary

from ..prompts.system import (
    build_system_prompt,
    build_turn_context,
)


class MiniCodexAgent:

    def __init__(
        self,
        llm,
        registry,
        planner=None,
        replanner=None,
        max_steps: int = 20,
        max_step_attempts: int = 5,
        max_context_tokens: int = 64000,
    ):
        self.llm = llm
        self.registry = registry

        # =====================================================
        # Reliable Tool Execution Boundary
        # =====================================================

        self.tool_executor = (
            ToolExecutor(
                registry
            )
        )

        # =====================================================
        # Task-Level Token Metrics
        # =====================================================

        self.token_metrics = (
            TokenMetrics()
        )

        # =====================================================
        # Context Budget
        # =====================================================

        self.context_budget = (
            ContextBudget(
                max_context_tokens=(
                    max_context_tokens
                )
            )
        )

        # =====================================================
        # Working Summary
        # =====================================================

        self.working_summary = (
            WorkingSummary(
                max_items=30
            )
        )

        # =====================================================
        # Planning Components
        # =====================================================

        self.planner = planner
        self.replanner = replanner

        self.max_steps = max_steps

        self.max_step_attempts = (
            max_step_attempts
        )

        # =====================================================
        # Current Task State
        # =====================================================

        self.active_plan: (
            AgentPlan | None
        ) = None

        self.active_user_request: (
            str | None
        ) = None

        # =====================================================
        # Progress Controller
        # =====================================================

        self.progress = (
            ProgressController(
                max_same_tool_repeats=2,
                progress_window=6,
                max_validation_no_progress=2,
            )
        )

        # =====================================================
        # Recovery Controller
        # =====================================================

        self.recovery = (
            RecoveryController(
                max_recovery_level=3
            )
        )

    # =========================================================
    # Main Entry
    # =========================================================

    def run(
        self,
        user_input: str,
        use_planning: bool = True,
    ) -> str:

        self.active_user_request = (
            user_input
        )

        self.active_plan = None

        # =====================================================
        # Reset Task State
        # =====================================================

        self.progress.reset(
            new_task=True
        )

        self.recovery.reset()

        self.token_metrics.reset()

        self.context_budget.reset()

        self.working_summary.reset()

        # =====================================================
        # Initial Planning
        # =====================================================

        if (
            use_planning
            and self.planner
        ):

            try:

                self.active_plan = (
                    self.planner
                    .create_plan(
                        user_input,
                        max_agent_steps=(
                            self.max_steps
                        ),
                        token_metrics=(
                            self.token_metrics
                        ),
                    )
                )

                self._print_plan(
                    self.active_plan
                )

            except Exception as e:

                print(
                    f"\n[Planning Failed] "
                    f"{type(e).__name__}: "
                    f"{e}"
                )

        # =====================================================
        # Agent Loop
        # =====================================================

        return run_agent_loop(
            self,
            user_input,
        )

    # =========================================================
    # Complete Plan Step
    # =========================================================

    def complete_plan_step(
        self,
    ) -> dict:

        if self.active_plan is None:

            return {
                "completed": False,
                "step_id": None,
                "step_description": None,
                "message": (
                    "No active plan."
                ),
            }

        step = (
            self.active_plan
            .complete_current_step()
        )

        if step is None:

            return {
                "completed": False,
                "step_id": None,
                "step_description": None,
                "message": (
                    "No active plan step."
                ),
            }

        self.recovery.mark_progress()

        self.progress.reset()

        self._print_plan(
            self.active_plan
        )

        return {
            "completed": True,
            "step_id": step.id,
            "step_description": (
                step.description
            ),
            "message": (
                f"Completed plan step "
                f"{step.id}: "
                f"{step.description}"
            ),
        }

    # =========================================================
    # Replan
    # =========================================================

    def replan(
        self,
        reason: str,
    ) -> dict:

        if self.active_plan is None:

            return {
                "replanned": False,
                "reason": reason,
                "failure_reason": (
                    "No active plan to revise."
                ),
                "message": (
                    "No active plan to revise."
                ),
            }

        if self.replanner is None:

            return {
                "replanned": False,
                "reason": reason,
                "failure_reason": (
                    "No replanner configured."
                ),
                "message": (
                    "No replanner configured."
                ),
            }

        if (
            self.active_user_request
            is None
        ):

            return {
                "replanned": False,
                "reason": reason,
                "failure_reason": (
                    "Original request unavailable."
                ),
                "message": (
                    "Original request unavailable."
                ),
            }

        try:

            new_plan = (
                self.replanner.replan(
                    user_request=(
                        self.active_user_request
                    ),
                    current_plan=(
                        self.active_plan
                    ),
                    reason=reason,
                    token_metrics=(
                        self.token_metrics
                    ),
                )
            )

        except Exception as e:

            error_message = (
                "Replanning failed: "
                f"{type(e).__name__}: "
                f"{e}"
            )

            return {
                "replanned": False,
                "reason": reason,
                "failure_reason": (
                    error_message
                ),
                "message": (
                    error_message
                ),
            }

        self.active_plan = (
            new_plan
        )

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

        return {
            "replanned": True,
            "reason": reason,
            "failure_reason": None,
            "message": (
                "Plan successfully revised. "
                "Continue execution using "
                "the new plan."
            ),
        }

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
            current_step.description
        )

        lowered = (
            text.lower()
        )

        english_keywords = (
            "fix",
            "modify",
            "change",
            "implement",
            "add",
            "update",
            "remove",
            "refactor",
            "rewrite",
            "replace",
            "create",
            "write",
        )

        chinese_keywords = (
            "修复",
            "修改",
            "实现",
            "增加",
            "添加",
            "更新",
            "删除",
            "重构",
            "新建",
            "重写",
            "替换",
            "写入",
            "编写",
        )

        if any(
            keyword in text
            for keyword
            in chinese_keywords
        ):
            return True

        return any(
            re.search(
                rf"\b{keyword}\b",
                lowered,
            )
            for keyword
            in english_keywords
        )

    # =========================================================
    # System Prompt
    # =========================================================

    def _build_system_prompt(
        self,
        **kwargs,
    ) -> str:

        return (
            build_system_prompt()
        )

    # =========================================================
    # Dynamic Turn Context
    # =========================================================

    def _build_turn_context(
        self,
        plan=None,
        current_step=None,
        remaining_agent_steps: (
            int | None
        ) = None,
        **kwargs,
    ) -> str:

        plan_text = (
            self._plan_to_text(
                plan
            )
            if plan
            else (
                "No explicit plan."
            )
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

        return build_turn_context(
            plan_text=(
                plan_text
            ),
            current_step_text=(
                current_step_text
            ),
            remaining_agent_steps=(
                remaining_agent_steps
            ),
            working_summary_text=(
                self.working_summary
                .render()
            ),
        )

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
                f"(failures="
                f"{step.attempts})"
            )
            for step
            in plan.all_steps()
        )

    # =========================================================
    # Print Plan
    # =========================================================

    def _print_plan(
        self,
        plan: AgentPlan,
    ) -> None:

        print(
            f"\n[Plan] "
            f"{plan.goal}"
        )

        for step in (
            plan.all_steps()
        ):

            print(
                f"{step.id}. "
                f"[{step.status.value}] "
                f"{step.description} "
                f"(failures="
                f"{step.attempts})"
            )