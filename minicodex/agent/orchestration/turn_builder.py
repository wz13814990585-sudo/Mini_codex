"""Build one provider turn from deterministic agent state."""

from __future__ import annotations

from dataclasses import dataclass

from ..context import compact_messages_for_pressure
from ..editing import EditStrategyHint
from ..execution_mode import ExecutionMode
from ..task_state import AgentPhase
from ...prompts.system import (
    build_fast_system_prompt,
    build_standard_system_prompt,
    build_system_prompt,
)


@dataclass(frozen=True)
class AgentTurn:
    messages: list[dict]
    tools: list[dict]


class PromptBuilder:
    def build(self, agent, **kwargs) -> str:
        del kwargs
        policy = getattr(agent, "execution_policy", None)
        if policy is not None and policy.compact_context:
            return build_fast_system_prompt()
        if policy is not None and policy.mode == ExecutionMode.STANDARD:
            return build_standard_system_prompt()
        return build_system_prompt()


class ToolSchemaProvider:
    def build(self, agent) -> list[dict]:
        if hasattr(agent, "get_tool_schemas"):
            return agent.get_tool_schemas()
        return agent.registry.get_schemas()


class ContextBuilder:
    """Build small phase-specific context from current deterministic state."""

    def __init__(self, edit_strategy: EditStrategyHint | None = None) -> None:
        self.edit_strategy = edit_strategy or EditStrategyHint()

    def build(self, agent, *, current_plan_step, remaining_agent_steps: int) -> str:
        state = agent.task_progress_state(remaining_agent_steps)
        targets = tuple(state.relevant_paths or state.target_paths)
        target_text = ", ".join(targets) if targets else "not explicit"
        sections = [
            f"Task: {state.user_request or getattr(agent, 'active_user_request', '')}",
            f"Intent: {state.intent.value}. Mode: {state.mode.value if state.mode else 'unknown'}. Phase: {state.phase.value}.",
            f"Targets: {target_text}. Remaining steps: {remaining_agent_steps}.",
        ]
        summary = agent.working_summary.render_relevant(targets, max_items=8)

        if state.phase == AgentPhase.INSPECTING:
            sections.append("Inspect only the minimum target code needed to decide the next action.")
            repo_fragment = str(getattr(agent, "repo_map_text", "") or "")[:1800]
            if repo_fragment:
                sections.append("Repository map:\n" + repo_fragment)
        elif state.phase == AgentPhase.ACTING:
            target = targets[0] if targets else None
            sections.append(self.edit_strategy.render(agent.workspace, target))
            if current_plan_step is not None:
                sections.append(
                    f"Current plan step: {current_plan_step.id}. {current_plan_step.description}"
                )
        elif state.phase == AgentPhase.VALIDATING:
            registered = set(getattr(agent.registry, "_tools", {}) or {})
            selection = agent.validation_selector.select(
                target_paths=targets,
                registered_tools=registered,
                revision=state.edit_revision,
                desired_purpose=(
                    "acceptance" if not state.acceptance_passed else "regression"
                ),
            )
            recommendation = (
                f"Run {selection.tool_name}"
                + (f" on {selection.path}" if selection.path else "")
                + f" as {selection.purpose}."
                if selection
                else "Obtain the missing targeted validation evidence."
            )
            sections.append("Validation recommendation: " + recommendation)
        elif state.phase == AgentPhase.FIXING:
            evidence = getattr(agent.validation_pipeline.state, "latest_evidence", None)
            details = getattr(evidence, "details", {}) or {}
            failure_paths = tuple(details.get("failure_paths", ()))
            sections.append(
                "Latest failure paths: "
                + (", ".join(failure_paths) if failure_paths else "use the current validation target")
                + ". Recover locally before broad search or replanning."
            )
        elif state.phase == AgentPhase.FINALIZING:
            decision = agent.completion_policy.evaluate(agent)
            sections.append("Only the remaining completion requirement matters: " + decision.reason)

        if summary:
            sections.append("Recent relevant facts:\n" + summary[-2200:])
        retrieved = getattr(agent, "_retrieved_long_term_memory", ()) or ()
        store = getattr(agent, "long_term_memory_store", None)
        if retrieved and store is not None:
            try:
                memory_text = str(store.render_retrieved(retrieved) or "").strip()
            except Exception:
                memory_text = ""
            if memory_text:
                sections.append("Advisory prior-task memory:\n" + memory_text[-1800:])
        return "\n\n".join(sections).strip() + "\n"


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
