from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolErrorCode(str, Enum):
    INVALID_ARGUMENT = "invalid_argument"
    STALE_CONTEXT = "stale_context"
    AMBIGUOUS_MATCH = "ambiguous_match"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    DEPENDENCY_MISSING = "dependency_missing"
    VALIDATION_FAILED = "validation_failed"
    ENVIRONMENT_FAILURE = "environment_failure"
    CONFLICT = "conflict"
    DUPLICATE_ACTION = "duplicate_action"
    SAFETY_BLOCKED = "safety_blocked"
    UNKNOWN = "unknown"


_ERROR_ALIASES = {
    "invalid_arguments": ToolErrorCode.INVALID_ARGUMENT,
    "invalid_argument": ToolErrorCode.INVALID_ARGUMENT,
    "stale_context": ToolErrorCode.STALE_CONTEXT,
    "ambiguous_match": ToolErrorCode.AMBIGUOUS_MATCH,
    "not_found": ToolErrorCode.NOT_FOUND,
    "symbol_not_found": ToolErrorCode.NOT_FOUND,
    "permission_denied": ToolErrorCode.PERMISSION_DENIED,
    "timeout": ToolErrorCode.TIMEOUT,
    "dependency_missing": ToolErrorCode.DEPENDENCY_MISSING,
    "missing_dependency": ToolErrorCode.DEPENDENCY_MISSING,
    "validation_failed": ToolErrorCode.VALIDATION_FAILED,
    "test_failure": ToolErrorCode.VALIDATION_FAILED,
    "environment_failure": ToolErrorCode.ENVIRONMENT_FAILURE,
    "workspace_conflict": ToolErrorCode.CONFLICT,
    "rollback_conflict": ToolErrorCode.CONFLICT,
    "conflict": ToolErrorCode.CONFLICT,
    "duplicate_call": ToolErrorCode.DUPLICATE_ACTION,
    "safety_blocked": ToolErrorCode.SAFETY_BLOCKED,
}


@dataclass
class ToolResult:
    success: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    llm_content: str | None = None
    error_code: ToolErrorCode | None = None

    def __post_init__(self) -> None:
        if self.success:
            self.error_code = None
            return
        if self.error_code is not None and not isinstance(self.error_code, ToolErrorCode):
            try:
                self.error_code = ToolErrorCode(str(self.error_code).strip().lower())
            except ValueError:
                self.error_code = ToolErrorCode.UNKNOWN
        if self.error_code is None:
            raw = str(
                self.data.get("edit_failure_type")
                or self.data.get("failure_type")
                or self.data.get("reason_code")
                or ""
            ).strip().lower()
            self.error_code = _ERROR_ALIASES.get(raw, ToolErrorCode.UNKNOWN)
        self.data.setdefault("error_code", self.error_code.value)

    def to_llm_text(self) -> str:
        parts = [self.summary]

        if self.llm_content:
            parts.append(self.llm_content)

        if self.error:
            code = self.error_code.value if self.error_code else ToolErrorCode.UNKNOWN.value
            parts.append(f"Error [{code}]: {self.error}")

        text = "\n\n".join(parts)
        # Full raw output belongs in trace/artifacts; provider context receives
        # one bounded observation so old logs cannot dominate future turns.
        if len(text) > 16_000:
            text = text[:15_800] + "\n\n[output truncated by Harness]"
        return text
