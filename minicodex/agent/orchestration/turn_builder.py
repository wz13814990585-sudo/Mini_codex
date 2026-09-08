"""Build one provider turn from deterministic agent state."""

from __future__ import annotations

from dataclasses import dataclass

from ..context import compact_messages_for_pressure


@dataclass(frozen=True)
class AgentTurn:
    messages: list[dict]
    tools: list[dict]


class TurnBuilder:
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
        system_prompt = agent._build_system_prompt(
            user_input=user_input,
            plan=agent.active_plan,
            current_step=current_plan_step,
            remaining_agent_steps=remaining_agent_steps,
        )
        messages = [{"role": "system", "content": system_prompt}, *history]
        build_context = getattr(agent, "_build_turn_context", None)
        if callable(build_context):
            messages.append(
                {
                    "role": "user",
                    "content": build_context(
                        plan=agent.active_plan,
                        current_step=current_plan_step,
                        remaining_agent_steps=remaining_agent_steps,
                    ),
                }
            )
        tools = (
            agent.get_tool_schemas()
            if hasattr(agent, "get_tool_schemas")
            else agent.registry.get_schemas()
        )
        return AgentTurn(messages=messages, tools=tools)
