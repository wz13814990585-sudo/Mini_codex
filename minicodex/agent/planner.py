import json

from agent.state import AgentPlan, PlanStep


class Planner:

    def __init__(self, llm):
        self.llm = llm

    def create_plan(
        self,
        user_request: str
    ) -> AgentPlan:

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a coding task planner. "
                    "Break the user's request into a small "
                    "number of concrete implementation steps. "
                    "Do not execute tools. "
                    "Return valid JSON only."
                )
            },
            {
                "role": "user",
                "content": f"""
Create an implementation plan for this request:

{user_request}

Return exactly this JSON format:

{{
    "goal": "short goal",
    "steps": [
        "step 1",
        "step 2",
        "step 3"
    ]
}}
"""
            }
        ]

        response = self.llm.chat(
            messages=messages,
            tools=None
        )

        raw_content = response.content.strip()

        # 防止模型偶尔返回 ```json ... ```
        if raw_content.startswith("```"):
            raw_content = raw_content.strip("`")

            if raw_content.startswith("json"):
                raw_content = raw_content[4:]

            raw_content = raw_content.strip()

        data = json.loads(
            raw_content
        )

        steps = [
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
            steps=steps
        )