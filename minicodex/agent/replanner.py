import json

from .metrics import TokenMetrics
from .state import (
    AgentPlan,
    PlanStep,
    StepStatus,
)


class Replanner:

    def __init__(
        self,
        llm,
    ):
        self.llm = llm

    # =========================================================
    # Replan
    # =========================================================

    def replan(
        self,
        user_request: str,
        current_plan: AgentPlan,
        reason: str,
        token_metrics: TokenMetrics | None = None,
    ) -> AgentPlan:

        # =====================================================
        # Completed Work
        # =====================================================

        completed_history = [
            *current_plan.completed_history,
            *(
                step
                for step
                in current_plan.steps
                if (
                    step.status
                    == StepStatus.COMPLETED
                )
            ),
        ]

        completed_steps = [
            step.description
            for step
            in completed_history
        ]

        remaining_steps = [
            step.description
            for step
            in current_plan.steps
            if (
                step.status
                != StepStatus.COMPLETED
            )
        ]

        # =====================================================
        # Build Replanning Prompt
        # =====================================================

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a coding task replanner. "
                    "Create a revised implementation "
                    "plan based on the original goal, "
                    "completed work, and new evidence. "
                    "Do not repeat completed work. "
                    "Return valid JSON only."
                ),
            },
            {
                "role": "user",
                "content": f"""
Original user request:

{user_request}

Current goal:

{current_plan.goal}

Completed steps:

{completed_steps}

Remaining or unfinished steps:

{remaining_steps}

Reason replanning is required:

{reason}

Return exactly:

{{
    "goal": "updated goal",
    "steps": [
        "next step 1",
        "next step 2"
    ]
}}
""",
            },
        ]

        # =====================================================
        # LLM Call
        # =====================================================

        llm_response = self.llm.chat(
            messages=messages,
            tools=None,
        )

        # =====================================================
        # Token Metrics
        # =====================================================

        if token_metrics is not None:

            token_metrics.record(
                llm_response.usage
            )

        # =====================================================
        # Extract Provider Message
        # =====================================================

        response = (
            llm_response.message
        )

        raw = (
            response.content
            or ""
        ).strip()

        # =====================================================
        # Remove Optional Markdown Fence
        # =====================================================

        if raw.startswith(
            "```"
        ):

            raw = (
                raw.strip("`")
            )

            if raw.startswith(
                "json"
            ):

                raw = (
                    raw[4:]
                )

            raw = (
                raw.strip()
            )

        # =====================================================
        # Parse Revised Plan
        # =====================================================

        data = json.loads(
            raw
        )

        # =====================================================
        # Prevent Completed Work From Returning
        # =====================================================

        completed_descriptions = {
            description
            .strip()
            .casefold()
            for description
            in completed_steps
        }

        revised_steps = [
            description
            for description
            in data["steps"]
            if (
                description
                .strip()
                .casefold()
                not in completed_descriptions
            )
        ]

        # =====================================================
        # Continue Step IDs
        # =====================================================

        next_step_id = (
            max(
                (
                    step.id
                    for step
                    in current_plan.all_steps()
                ),
                default=0,
            )
            + 1
        )

        new_steps = [
            PlanStep(
                id=index,
                description=description,
            )
            for index, description
            in enumerate(
                revised_steps,
                start=next_step_id,
            )
        ]

        return AgentPlan(
            goal=data["goal"],
            steps=new_steps,
            completed_history=(
                completed_history
            ),
        )