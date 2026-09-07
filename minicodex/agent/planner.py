import json

from .metrics import TokenMetrics
from .message_protocol import validate_tool_message_protocol
from .plan_quality import PlanNormalizer
from .state import AgentPlan, PlanStep


class Planner:

    def __init__(
        self,
        llm,
        normalizer: PlanNormalizer | None = None,
    ):
        self.llm = llm
        self.normalizer = normalizer or PlanNormalizer()

    # =========================================================
    # Create Plan
    # =========================================================

    def create_plan(
        self,
        user_request: str,
        max_agent_steps: int = 20,
        token_metrics: TokenMetrics | None = None,
    ) -> AgentPlan:

        max_plan_steps = max(
            3,
            min(
                6,
                max_agent_steps // 3 or 3,
            ),
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a coding task planner. "
                    "Break the user's request into a small "
                    "number of concrete implementation steps. "
                    "Give each step one independently verifiable "
                    "outcome; do not bundle several game features "
                    "or unrelated behaviors into one large step. "
                    "Do not execute tools. "
                    "Return valid JSON only."
                ),
            },
            {
                "role": "user",
                "content": f"""
Create an implementation plan for this request:

{user_request}

The executing agent has only {max_agent_steps} tool-using
turns. Keep the plan short: at most {max_plan_steps}
concrete steps. Prefer 4 steps or fewer.

Return exactly this JSON format:

{{
    "goal": "short goal",
    "steps": [
        {{
            "description": "step 1",
            "acceptance_criteria": [
                {{"type": "file_exists", "path": "relative/path"}},
                {{"type": "contains_all", "path": "relative/path", "texts": ["required marker"]}}
            ]
        }},
        {{
            "description": "semantic-only step 2",
            "acceptance_criteria": []
        }}
    ]
}}

Only use machine criteria that are definitely testable. Supported
criterion types are file_exists, contains_text, contains_all,
static_web_validation, and metric_at_least. Use an empty list when
completion requires semantic judgment.
""",
            },
        ]

        data, steps, raw_content = self._request_plan(
            messages=messages,
            max_plan_steps=max_plan_steps,
            token_metrics=token_metrics,
        )
        quality = self.normalizer.validate(steps)

        if quality.should_regenerate:
            details = "; ".join(
                f"step {issue.step_id}: {issue.message}"
                for issue in quality.issues
            )
            messages.extend(
                [
                    {"role": "assistant", "content": raw_content},
                    {
                        "role": "user",
                        "content": (
                            "Regenerate the plan once. Replace process-only "
                            "steps with concrete outcomes and split broad "
                            "semantic steps into smaller independently "
                            f"verifiable outcomes. Problems: {details}"
                        ),
                    },
                ]
            )
            data, steps, _ = self._request_plan(
                messages=messages,
                max_plan_steps=max_plan_steps,
                token_metrics=token_metrics,
            )
            quality = self.normalizer.validate(steps)
            if quality.has_process_only_steps:
                raise ValueError(
                    "Planner returned process-only steps after one "
                    "regeneration attempt."
                )

        return AgentPlan(
            goal=data["goal"],
            steps=steps,
        )

    def _request_plan(
        self,
        *,
        messages: list,
        max_plan_steps: int,
        token_metrics: TokenMetrics | None,
    ) -> tuple[dict, list[PlanStep], str]:
        validate_tool_message_protocol(messages)
        llm_response = self.llm.chat(messages=messages, tools=None)
        if token_metrics is not None:
            token_metrics.record(llm_response.usage)

        raw_content = str(llm_response.message.content or "").strip()
        if raw_content.startswith("```"):
            raw_content = raw_content.strip("`")
            if raw_content.startswith("json"):
                raw_content = raw_content[4:]
            raw_content = raw_content.strip()

        data = json.loads(raw_content)
        steps = [
            PlanStep.from_payload(step_id=index, payload=payload)
            for index, payload in enumerate(
                data["steps"][:max_plan_steps],
                start=1,
            )
        ]
        return data, steps, raw_content
