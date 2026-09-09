"""Build one provider turn from deterministic agent state."""

from __future__ import annotations

from dataclasses import dataclass

from ..context import compact_messages_for_pressure
from .context_builder import ContextBuilder
from .prompt_builder import PromptBuilder
from .tool_schema_provider import ToolSchemaProvider


@dataclass(frozen=True)
class AgentTurn:
    messages: list[dict]
    tools: list[dict]


class TurnBuilder:
    def __init__(
        self,
        prompt_builder: PromptBuilder | None = None,
        context_builder: ContextBuilder | None = None,
        tool_schema_provider: ToolSchemaProvider | None = None,
    ) -> None:
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.context_builder = context_builder or ContextBuilder()
        self.tool_schema_provider = tool_schema_provider or ToolSchemaProvider()

    def build(
        self,
        agent,
        *,
        history: list[dict],
        user_input: str,
        current_plan_step,
        remaining_agent_steps: int,
    ) -> AgentTurn:
        compact_messages_for_pressure(history, agent.context_budget.pressure)
        system_prompt = self.prompt_builder.build(
            agent,
            user_input=user_input,
            plan=agent.active_plan,
            current_step=current_plan_step,
            remaining_agent_steps=remaining_agent_steps,
        )
        messages = [{"role": "system", "content": system_prompt}, *history]
        messages.append(
            {
                "role": "user",
                "content": self.context_builder.build(
                    agent,
                    current_plan_step=current_plan_step,
                    remaining_agent_steps=remaining_agent_steps,
                ),
            }
        )
        tools = self.tool_schema_provider.build(agent)
        return AgentTurn(messages=messages, tools=tools)
