import json

from agent.state import AgentPlan, PlanStep, StepStatus


class Replanner:

    def __init__(self, llm):
        self.llm = llm

    def replan(
        self,
        user_request: str,
        current_plan: AgentPlan,
        reason: str
    ) -> AgentPlan:

        completed_steps = [
            step.description
            for step in current_plan.steps
            if step.status == StepStatus.COMPLETED
        ]

        remaining_steps = [
            step.description
            for step in current_plan.steps
            if step.status != StepStatus.COMPLETED
        ]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a coding task replanner. "
                    "Create a revised implementation plan based on "
                    "the original goal, completed work, and new evidence. "
                    "Do not repeat completed work. "
                    "Return valid JSON only."
                )
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
"""
            }
        ]

        response = self.llm.chat(
            messages=messages,
            tools=None
        )

        raw = response.content.strip()

        if raw.startswith("```"):
            raw = raw.strip("`")

            if raw.startswith("json"):
                raw = raw[4:]

            raw = raw.strip()

        data = json.loads(raw)

        new_steps = [
            PlanStep(
                id=index,
                description=description
            )
            for index, description in enumerate(
                data["steps"],
                start=1
            )
        ]

        return AgentPlan(
            goal=data["goal"],
            steps=new_steps
        )