"""Resolve which tool schemas the LLM may see for one turn."""

from __future__ import annotations

from dataclasses import dataclass

from ..progress.action_controller import ActionController
from ..progress.executable_tool_policy import (
    ExecutableToolDecision,
    ExecutableToolPolicy,
    ExecutableToolPolicyState,
)
from ..task_state import AgentPhase


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
    """Build ExecutableToolPolicyState from live agent controllers."""

    def snapshot(self, agent) -> ToolAvailabilitySnapshot:
        state = self.build_state(agent)
        decision = ExecutableToolPolicy.resolve(state)
        return ToolAvailabilitySnapshot(state=state, decision=decision)

    def build_state(self, agent) -> ExecutableToolPolicyState:
        action = getattr(agent, "action_controller", None)
        finalization = getattr(agent, "finalization", None)
        policy = getattr(agent, "execution_policy", None)
        task_state = getattr(agent, "task_state", None)

        phase = getattr(action, "phase", None)
        task_phase = getattr(task_state, "phase", None)
        # Keep schema snapshot on the same phase ActionController will guard
        # with after update_context (canonical TaskState.phase).
        if task_phase is not None:
            phase = task_phase
            if action is not None and getattr(action, "phase", None) != task_phase:
                action.phase = task_phase
        if phase is None:
            phase = AgentPhase.INSPECTING
        inspection_budget = None
        if action is not None and policy is not None:
            inspection_budget = action._inspection_limit(policy)

        exposed = getattr(policy, "exposed_tool_names", None) if policy else None
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
                getattr(
                    ActionController,
                    "UNRESOLVED_INSPECTION_LIMIT",
                    1,
                )
            ),
            next_contract_type=str(getattr(action, "next_contract_type", "") or ""),
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
            exposed_tool_names=frozenset(exposed) if exposed is not None else None,
        )

    def filter_schemas(self, agent, schemas: list[dict]) -> list[dict]:
        """Keep only schemas whose capabilities intersect the allowed set."""

        snapshot = self.snapshot(agent)
        registry = getattr(agent, "registry", None)
        allowed = snapshot.allowed_capabilities
        denied = snapshot.denied_tool_names
        mode_allowlist = snapshot.state.exposed_tool_names

        filtered: list[dict] = []
        for schema in schemas:
            name = schema.get("function", {}).get("name")
            if not name:
                continue
            if name in denied:
                continue
            if mode_allowlist is not None and name not in mode_allowlist:
                continue
            if registry is None or name not in getattr(registry, "_tools", {}):
                # Unknown / stub tools: keep only if mode allowlist already passed.
                filtered.append(schema)
                continue
            caps = frozenset(registry.capabilities_for(name))
            if not caps:
                filtered.append(schema)
                continue
            if caps & allowed:
                filtered.append(schema)
        return filtered
