import json

from ..observability import TokenMetrics
from ..orchestration.message_protocol import validate_tool_message_protocol
from .plan_quality import PlanNormalizer
from .state import (
    AgentPlan,
    PlanStep,
    StepStatus,
)


class Replanner:

    def __init__(
        self,
        llm,
        normalizer: PlanNormalizer | None = None,
    ):
        self.llm = llm
        self.normalizer = normalizer or PlanNormalizer()

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
                    "你是编码任务重规划器。"
                    "根据原始目标、已完成工作与新证据，"
                    "创建修订后的实现计划。"
                    "不要重复已完成的工作。"
                    "只返回合法 JSON。"
                    "goal 与各 step 的 description 请使用简洁中文。"
                ),
            },
            {
                "role": "user",
                "content": f"""
原始用户请求：

{user_request}

当前目标：

{current_plan.goal}

已完成步骤：

{completed_steps}

剩余或未完成步骤：

{remaining_steps}

需要重规划的原因：

{reason}

严格返回：

{{
    "goal": "更新后的目标",
    "steps": [
        {{
            "description": "下一步 1",
            "acceptance_criteria": []
        }}
    ]
}}

每个 acceptance_criteria 列表只能使用 file_exists、
contains_text、contains_all、static_web_validation 或
metric_at_least。纯语义步骤请使用 []。
""",
            },
        ]

        # =====================================================
        # LLM Call
        # =====================================================

        validate_tool_message_protocol(messages)

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
            payload
            for payload
            in data["steps"]
            if (
                self._description(
                    payload
                )
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
            PlanStep.from_payload(
                step_id=index,
                payload=payload,
            )
            for index, payload
            in enumerate(
                revised_steps,
                start=next_step_id,
            )
        ]

        self.normalizer.normalize(new_steps)

        return AgentPlan(
            goal=data["goal"],
            steps=new_steps,
            completed_history=(
                completed_history
            ),
        )

    @staticmethod
    def _description(payload) -> str:
        if isinstance(payload, str):
            return payload

        if isinstance(payload, dict):
            return str(
                payload.get("description", "")
            )

        return ""
