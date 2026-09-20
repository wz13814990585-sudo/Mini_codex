import json

from ..observability import TokenMetrics
from ..orchestration.message_protocol import validate_tool_message_protocol
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
        max_plan_steps: int | None = None,
        token_metrics: TokenMetrics | None = None,
    ) -> AgentPlan:

        if max_plan_steps is None:
            max_plan_steps = max(3, min(6, max_agent_steps // 3 or 3))
        else:
            max_plan_steps = max(1, min(6, int(max_plan_steps)))

        messages = [
            {
                "role": "system",
                "content": (
                    "你是编码任务规划器。"
                    "将用户请求拆成少量具体的实现步骤。"
                    "每一步只对应一个可独立验证的结果；"
                    "不要把多个游戏功能或不相关行为捆成一步。"
                    "不要执行工具。"
                    "只返回合法 JSON。"
                    "goal 与各 step 的 description 请使用简洁中文。"
                ),
            },
            {
                "role": "user",
                "content": f"""
为以下请求创建实现计划：

{user_request}

执行代理只有 {max_agent_steps} 次可使用工具的回合。
保持计划简短：最多 {max_plan_steps} 个具体步骤。
优先不超过 4 步。

严格按以下 JSON 格式返回：

{{
    "goal": "简短目标",
    "steps": [
        {{
            "description": "步骤 1",
            "expected_targets": ["relative/path"],
            "dependency_ids": [],
            "acceptance_criteria": [
                {{"type": "file_exists", "path": "relative/path"}},
                {{"type": "contains_all", "path": "relative/path", "texts": ["required marker"]}}
            ]
        }},
        {{
            "description": "仅语义判断的步骤 2",
            "expected_targets": ["relative/path"],
            "dependency_ids": [1],
            "acceptance_criteria": []
        }}
    ]
}}

只使用确实可机器检验的准则。支持的 criterion type 为
file_exists、contains_text、contains_all、
static_web_validation 与 metric_at_least。
当完成需要语义判断时，使用空列表。
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
                f"步骤 {issue.step_id}：{issue.message}"
                for issue in quality.issues
            )
            messages.extend(
                [
                    {"role": "assistant", "content": raw_content},
                    {
                        "role": "user",
                        "content": (
                            "请重新生成一次计划。将仅流程性步骤"
                            "替换为具体结果，并将过宽的语义步骤"
                            "拆成更小、可独立验证的结果。"
                            f"问题：{details}"
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
            if quality.issues:
                invalid_ids = {
                    issue.step_id
                    for issue in quality.issues
                    if issue.code
                    in {
                        "process_only",
                        "repeated_verification",
                        "broad_semantic",
                    }
                }
                steps = [step for step in steps if step.id not in invalid_ids]
                if not steps:
                    steps = [
                        PlanStep(
                            id=1,
                            description=(
                                "所请求的实现结果已存在"
                            ),
                        ),
                        PlanStep(
                            id=2,
                            description="验收验证通过",
                        ),
                    ]
                for index, step in enumerate(steps, start=1):
                    step.id = index

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
