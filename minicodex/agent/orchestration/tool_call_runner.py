"""Prepare, restrict, deduplicate, and execute one provider tool call."""

from __future__ import annotations

from dataclasses import dataclass, replace
from ..runtime.tool_types import PreparedToolCall
from ..editing.edit_verifier import DEFER_SYNTAX
from ..editing.edit_intent import EditIntent, ACTIVE_EDIT_INTENT

from ...tools.results import ToolResult
from ..reason_codes import ReasonCode, reason_value
from .tool_batch import ToolRestriction, resolve_tool_restriction


@dataclass(frozen=True)
class ToolCallRun:
    tool_name: str
    arguments: dict
    result: ToolResult
    preparation_failed: bool = False
    restriction: ToolRestriction | None = None
    duplicate_blocked: bool = False


class ToolCallRunner:
    """Own prepare → restrict → duplicate-check → safe execute for one call."""

    def run(self, agent, tool_call) -> ToolCallRun:
        refresh = getattr(agent, "refresh_workspace_facts", None)
        if refresh is not None:
            refresh()
        tool_name = tool_call.function.name
        prepared = agent.tool_executor.prepare(
            tool_name=tool_name,
            raw_arguments=tool_call.function.arguments,
        )
        if prepared.error is not None:
            return ToolCallRun(tool_name, {}, prepared.error, preparation_failed=True)

        arguments = prepared.arguments
        restriction = resolve_tool_restriction(agent, tool_name, arguments)
        if restriction is not None:
            result = ToolResult(
                success=False,
                summary=f"Tool call '{tool_name}' was blocked by the active execution control policy.",
                data={
                    "tool_name": tool_name,
                    "failure_type": restriction.failure_type,
                    "reason_code": reason_value(restriction.reason_code),
                    **restriction.data,
                },
                error=restriction.reason,
            )
            return ToolCallRun(tool_name, arguments, result, restriction=restriction)

        allowed, duplicate_reason = agent.progress.check_duplicate_tool_call(
            tool_name,
            arguments,
            workspace_revision=getattr(agent.task_state, "edit_revision", 0),
        )
        ledger = agent.validation_pipeline.state
        latest = ledger.latest_evidence
        if latest is not None and (latest.unstable or latest.details.get("workspace_changed_during_validation")) and latest.tool_name == tool_name:
            target = arguments.get("path", arguments.get("command", ""))
            attempts = sum(e.edit_revision == ledger.edit_revision and e.validation_key == latest.validation_key
                           for e in ledger.evidence_history)
            if target == latest.path and attempts < 6:
                allowed = True
        if not allowed:
            result = ToolResult(
                success=False,
                summary=f"Tool call '{tool_name}' was blocked as a duplicate.",
                data={
                    "tool_name": tool_name,
                    "failure_type": "duplicate_call",
                    "reason_code": ReasonCode.DUPLICATE_TOOL_CALL.value,
                },
                error=duplicate_reason,
            )
            return ToolCallRun(tool_name, arguments, result, duplicate_blocked=True)

        unit = getattr(agent.task_state, "work_unit", None)
        token = DEFER_SYNTAX.set(bool(unit.permits_intermediate_syntax if unit else len(agent.task_state.target_paths) > 1))
        declared_intent = arguments.get("edit_intent")
        intent = EditIntent.from_arguments(arguments)
        if isinstance(declared_intent, dict):
            intent = EditIntent(
                path=str(declared_intent.get("path", "")),
                expected_text=str(declared_intent.get("expected_text", "")),
                removed_text=str(declared_intent.get("removed_text", "")),
                symbol=str(declared_intent.get("symbol", "")),
            )
        intent = replace(intent, allow_contract_change=bool(getattr(
            getattr(agent, "safety_policy", None), "test_contract_change_authorized", False)))
        intent_token = ACTIVE_EDIT_INTENT.set(intent)
        try:
            execution = agent.tool_executor.execute_prepared(PreparedToolCall(
                tool_name, {k: v for k, v in arguments.items() if k not in {"validation_check", "edit_intent"}}
            ))
        finally:
            DEFER_SYNTAX.reset(token)
            ACTIVE_EDIT_INTENT.reset(intent_token)
        return ToolCallRun(tool_name, arguments, execution.result)
