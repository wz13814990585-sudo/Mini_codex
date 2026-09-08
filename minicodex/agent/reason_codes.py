"""Stable machine-readable reasons shared by tools and orchestration."""

from enum import Enum


class ReasonCode(str, Enum):
    INSPECTION_LIMIT = "inspection_limit"
    STALE_CONTEXT = "stale_context"
    AMBIGUOUS_MATCH = "ambiguous_match"
    SYMBOL_NOT_FOUND = "symbol_not_found"
    INVALID_RANGE = "invalid_range"
    ACCEPTANCE_MISSING = "acceptance_missing"
    REGRESSION_MISSING = "regression_missing"
    FULL_REGRESSION_MISSING = "full_regression_missing"
    UNSAFE_COMMAND = "unsafe_command"
    DUPLICATE_TOOL_CALL = "duplicate_tool_call"
    PLAN_INCOMPLETE = "plan_incomplete"
    DEPENDENCY_MANIFEST_REQUIRED = "dependency_manifest_required"
    MAX_STEPS = "max_steps"
    BLOCKED = "blocked"


def reason_value(reason: ReasonCode | str | None) -> str | None:
    if reason is None:
        return None
    return reason.value if isinstance(reason, ReasonCode) else str(reason)
