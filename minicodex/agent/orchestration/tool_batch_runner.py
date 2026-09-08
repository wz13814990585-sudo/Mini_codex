"""Deterministic execution of one call within an atomic provider tool batch."""

from __future__ import annotations

from dataclasses import dataclass

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


class ToolBatchRunner:
    """Own parse → restrict → de-duplicate → safe execution ordering."""

    def run_call(self, agent, tool_call) -> ToolCallRun:
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
            tool_name, arguments
        )
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

        execution = agent.tool_executor.execute_prepared(prepared)
        return ToolCallRun(tool_name, arguments, execution.result)
