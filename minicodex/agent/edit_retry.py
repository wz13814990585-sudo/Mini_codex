"""Bounded deterministic recovery for edits based on stale source context."""

from __future__ import annotations

from dataclasses import dataclass


EDIT_TOOLS = frozenset(
    {"patch_file", "replace_lines", "replace_symbol", "write_file"}
)


@dataclass
class PendingEditRetry:
    path: str
    edit_tool: str
    start_line: int | None = None
    end_line: int | None = None
    read_completed: bool = False
    retry_used: bool = False


class EditRetryPolicy:
    """Allow exactly one targeted refresh and one replacement edit attempt."""

    def __init__(self) -> None:
        self.pending: PendingEditRetry | None = None

    def reset(self) -> None:
        self.pending = None

    def restriction_reason(self, tool_name: str, arguments: dict) -> str | None:
        pending = self.pending
        if pending is None:
            return None
        path = str(arguments.get("path", "") or "").strip()
        if not pending.read_completed:
            if tool_name == "read_file" and path == pending.path:
                if self._read_covers_pending(arguments, pending):
                    return None
                return (
                    f"Read the affected range around line {pending.start_line} in "
                    f"{pending.path}; the requested chunk does not cover it."
                )
            return (
                f"The previous edit used stale context. Read only the affected "
                f"region of {pending.path} before retrying the edit."
            )
        if tool_name in EDIT_TOOLS and path == pending.path:
            return None
        return (
            f"Fresh context for {pending.path} is available. Retry one targeted "
            "edit now; broad search or unrelated actions are not allowed."
        )

    def observe(self, tool_name: str, arguments: dict, result) -> str | None:
        failure_type = str(result.data.get("failure_type", "") or "")
        path = str(result.data.get("path", arguments.get("path", "")) or "").strip()

        if tool_name in EDIT_TOOLS and failure_type == "stale_context" and path:
            if self.pending is not None and self.pending.read_completed:
                self.pending = None
                return (
                    "The single stale-context edit retry also failed. Do not loop; "
                    "report the concrete conflict or choose a different evidenced edit."
                )
            self.pending = PendingEditRetry(
                path=path,
                edit_tool=tool_name,
                start_line=self._optional_int(result.data.get("start_line")),
                end_line=self._optional_int(result.data.get("end_line")),
            )
            return self.read_instruction()

        pending = self.pending
        if pending is None:
            return None
        if tool_name == "read_file" and path == pending.path and result.success:
            pending.read_completed = True
            return (
                f"The affected source in {pending.path} is fresh. Retry the "
                f"{pending.edit_tool} edit once using the current content."
            )
        if tool_name in EDIT_TOOLS and path == pending.path:
            pending.retry_used = True
            self.pending = None
        return None

    def read_instruction(self) -> str:
        pending = self.pending
        if pending is None:
            return ""
        range_text = ""
        if pending.start_line is not None:
            end = pending.end_line or pending.start_line
            range_text = f" around lines {pending.start_line}-{end}"
        return (
            f"The edit was rejected because its source context is stale. Read "
            f"{pending.path}{range_text} once, then retry one targeted edit. "
            "Do not broaden the search or replan."
        )

    @staticmethod
    def _optional_int(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _read_covers_pending(arguments: dict, pending: PendingEditRetry) -> bool:
        if pending.start_line is None:
            return True
        try:
            start = max(1, int(arguments.get("offset", 1)))
            limit = max(1, int(arguments.get("limit", 200)))
        except (TypeError, ValueError):
            return False
        end = start + limit - 1
        pending_end = pending.end_line or pending.start_line
        return start <= pending_end and end >= pending.start_line
