"""Build one provider turn from deterministic agent state.

Prompt selection, schema decoration, and schema availability all belong to
the same operation: constructing the next model turn.  Keeping them together
avoids a chain of tiny pass-through services on the hottest orchestration
path, while ``ExecutableToolPolicy`` remains the one pure source of tool
availability decisions.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from ..context import compact_messages_for_pressure
from ..progress.action_controller import ActionController
from ..progress.executable_tool_policy import (
    ExecutableToolDecision,
    ExecutableToolPolicy,
    ExecutableToolPolicyState,
)
from ..routing import ExecutionMode
from ..task_state import AgentPhase
from ...prompts.system import (
    build_fast_system_prompt,
    build_standard_system_prompt,
    build_system_prompt,
)
from .context_builder import ContextBuilder


class PromptBuilder:
    """Select the system prompt for the active execution policy."""

    def build(self, agent, **kwargs) -> str:
        del kwargs
        policy = getattr(agent, "execution_policy", None)
        if policy is not None and policy.compact_context:
            return build_fast_system_prompt()
        if policy is not None and policy.mode == ExecutionMode.STANDARD:
            return build_standard_system_prompt()
        return build_system_prompt()


@dataclass(frozen=True)
class ToolAvailabilitySnapshot:
    state: ExecutableToolPolicyState
    decision: ExecutableToolDecision

    @property
    def allowed_capabilities(self) -> frozenset[str]:
        return self.decision.allowed_capabilities

    @property
    def denied_tool_names(self) -> frozenset[str]:
        return self.decision.denied_tool_names


class ToolAvailabilityResolver:
    """Translate live task state into the pure executable-tool policy."""

    def snapshot(self, agent) -> ToolAvailabilitySnapshot:
        state = self.build_state(agent)
        return ToolAvailabilitySnapshot(
            state=state,
            decision=ExecutableToolPolicy.resolve(state),
        )

    def build_state(self, agent) -> ExecutableToolPolicyState:
        action = getattr(agent, "action_controller", None)
        finalization = getattr(agent, "finalization", None)
        policy = getattr(agent, "execution_policy", None)
        task_state = getattr(agent, "task_state", None)

        phase = getattr(task_state, "phase", None) or getattr(action, "phase", None)
        if phase is None:
            phase = AgentPhase.INSPECTING
        if action is not None and getattr(action, "phase", None) != phase:
            action.phase = phase

        inspection_budget = (
            action._inspection_limit(policy)
            if action is not None and policy is not None
            else None
        )
        exposed = getattr(policy, "exposed_tool_names", None) if policy else None
        unit = getattr(task_state, "work_unit", None)
        milestone_due = bool(
            unit is not None
            and not bool(getattr(unit, "closed", False))
            and bool(getattr(unit, "milestone_due", False))
        )

        retry = getattr(agent, "edit_retry", None)
        pending = getattr(retry, "pending", None) if retry is not None else None
        edit_retry_needs_read = False
        edit_retry_path = ""
        if pending is not None and not bool(getattr(pending, "read_completed", False)):
            failure = getattr(pending, "failure_type", "")
            failure_value = getattr(failure, "value", failure)
            if str(failure_value or "") != "symbol_not_found":
                edit_retry_needs_read = True
                edit_retry_path = str(getattr(pending, "path", "") or "")

        return ExecutableToolPolicyState(
            phase=phase,
            action_required=bool(getattr(action, "action_required", False)),
            consecutive_inspections=int(
                getattr(action, "consecutive_inspections", 0) or 0
            ),
            validation_inspections=int(
                getattr(action, "validation_inspections", 0) or 0
            ),
            inspection_budget=inspection_budget,
            unresolved_inspection_limit=int(
                getattr(ActionController, "UNRESOLVED_INSPECTION_LIMIT", 1)
            ),
            next_contract_type=str(
                getattr(action, "next_contract_type", "") or ""
            ),
            next_required_check_id=str(
                getattr(action, "next_required_check_id", "") or ""
            ),
            validator_resolution_status=str(
                getattr(action, "validator_resolution_status", "") or ""
            ),
            validation_paths=tuple(getattr(action, "validation_paths", ()) or ()),
            target_paths=tuple(getattr(action, "target_paths", ()) or ()),
            has_edit=bool(getattr(action, "has_edit", False)),
            finalization_active=bool(getattr(finalization, "active", False)),
            allow_proof_inspection=bool(
                getattr(finalization, "allow_proof_inspection", False)
            ),
            enable_replan=bool(getattr(policy, "enable_replan", False)),
            exposed_tool_names=(
                frozenset(exposed) if exposed is not None else None
            ),
            milestone_due=milestone_due,
            edit_retry_needs_read=edit_retry_needs_read,
            edit_retry_path=edit_retry_path,
        )

    def filter_schemas(self, agent, schemas: list[dict]) -> list[dict]:
        snapshot = self.snapshot(agent)
        registry = getattr(agent, "registry", None)
        allowed = snapshot.allowed_capabilities
        denied = snapshot.denied_tool_names
        mode_allowlist = snapshot.state.exposed_tool_names

        filtered: list[dict] = []
        for schema in schemas:
            name = schema.get("function", {}).get("name")
            if not name or name in denied:
                continue
            if mode_allowlist is not None and name not in mode_allowlist:
                continue
            if registry is None or name not in getattr(registry, "_tools", {}):
                filtered.append(schema)
                continue
            capabilities = frozenset(registry.capabilities_for(name))
            if not capabilities or capabilities & allowed:
                filtered.append(schema)
        return filtered


class ToolSchemaProvider:
    """Decorate backend schemas with Harness metadata, then filter them."""

    def __init__(
        self,
        availability: ToolAvailabilityResolver | None = None,
    ) -> None:
        self.availability = availability or ToolAvailabilityResolver()

    def build(self, agent) -> list[dict]:
        base_schemas = getattr(agent, "get_base_tool_schemas", None)
        if callable(base_schemas):
            schemas = copy.deepcopy(base_schemas())
        else:
            current_schemas = getattr(agent, "get_tool_schemas", None)
            schemas = copy.deepcopy(
                current_schemas()
                if callable(current_schemas)
                else agent.registry.get_schemas()
            )
        for schema in schemas:
            function = schema["function"]
            capabilities = agent.registry.capabilities_for(function["name"])
            properties = function["parameters"].setdefault("properties", {})
            if "code.edit" in capabilities:
                properties["edit_intent"] = {
                    "type": "object",
                    "description": (
                        "Independent expected post-edit state, not the patch mechanism."
                    ),
                    "properties": {
                        "path": {"type": "string"},
                        "expected_text": {"type": "string"},
                        "removed_text": {"type": "string"},
                        "symbol": {"type": "string"},
                    },
                    "required": ["path", "expected_text"],
                    "additionalProperties": False,
                }
            if capabilities & {
                "test.run",
                "process.run",
                "validation.static_web",
                "validation.browser",
                "service.validate",
            }:
                properties["validation_check"] = {
                    "type": "string",
                    "description": (
                        "Exact V-id from the current verification contracts."
                    ),
                }
        return self.availability.filter_schemas(agent, schemas)


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
