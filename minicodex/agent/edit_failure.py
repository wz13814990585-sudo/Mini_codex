"""Typed edit failures and their bounded recovery meaning."""

from __future__ import annotations

from enum import Enum

from .reason_codes import ReasonCode


class EditFailureType(str, Enum):
    STALE_CONTEXT = "stale_context"
    AMBIGUOUS_MATCH = "ambiguous_match"
    SYMBOL_NOT_FOUND = "symbol_not_found"
    INVALID_RANGE = "invalid_range"
    NO_CHANGE = "no_change"
    PERMISSION_DENIED = "permission_denied"
    UNKNOWN = "unknown"


def classify_edit_exception(tool_name: str, error: Exception) -> EditFailureType:
    if tool_name not in {"patch_file", "replace_lines", "replace_symbol", "write_file"}:
        return EditFailureType.UNKNOWN
    if isinstance(error, PermissionError):
        return EditFailureType.PERMISSION_DENIED
    text = str(error).casefold()
    if "would not change" in text:
        return EditFailureType.NO_CHANGE
    if "line range" in text or "start_line" in text or "end_line" in text:
        return EditFailureType.INVALID_RANGE
    if "ambiguous" in text or "multiple symbol" in text:
        return EditFailureType.AMBIGUOUS_MATCH
    if "symbol" in text and ("not found" in text or "no exact" in text):
        return EditFailureType.SYMBOL_NOT_FOUND
    return EditFailureType.UNKNOWN


def reason_for_edit_failure(failure: EditFailureType) -> ReasonCode | None:
    return {
        EditFailureType.STALE_CONTEXT: ReasonCode.STALE_CONTEXT,
        EditFailureType.AMBIGUOUS_MATCH: ReasonCode.AMBIGUOUS_MATCH,
        EditFailureType.SYMBOL_NOT_FOUND: ReasonCode.SYMBOL_NOT_FOUND,
        EditFailureType.INVALID_RANGE: ReasonCode.INVALID_RANGE,
    }.get(failure)
