"""Bounded deterministic recovery for edits based on stale source context."""

from __future__ import annotations

from dataclasses import dataclass

from .edit_failure import EditFailureType


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
    failure_type: EditFailureType = EditFailureType.STALE_CONTEXT
    symbol: str | None = None


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
        if pending.failure_type == EditFailureType.SYMBOL_NOT_FOUND:
            if not pending.read_completed:
                if tool_name == "search_symbol":
                    return None
                return "未找到请求的符号。请先调用一次 search_symbol 再重试。"
            if tool_name == "replace_symbol":
                return None
            return "符号候选已可用。请用更精确的范围重试一次 replace_symbol。"
        if not pending.read_completed:
            if tool_name == "read_file" and path == pending.path:
                if self._read_covers_pending(arguments, pending):
                    return None
                return (
                    f"请读取 {pending.path} 中约第 {pending.start_line} 行附近的受影响范围；"
                    f"当前请求的片段未覆盖该区域。"
                )
            return (
                f"上次编辑使用了过期上下文。请先只读取 {pending.path} "
                f"的受影响区域，再重试编辑。"
            )
        if tool_name in EDIT_TOOLS and path == pending.path:
            return None
        return (
            f"{pending.path} 的最新上下文已可用。请立即重试一次定向编辑；"
            "不允许扩大搜索或执行无关操作。"
        )

    def observe(self, tool_name: str, arguments: dict, result) -> str | None:
        failure_type = str(
            result.data.get("edit_failure_type", result.data.get("failure_type", "")) or ""
        )
        path = str(result.data.get("path", arguments.get("path", "")) or "").strip()

        typed_failure = (
            EditFailureType(failure_type)
            if failure_type in {item.value for item in EditFailureType}
            else EditFailureType.UNKNOWN
        )
        if tool_name in EDIT_TOOLS and typed_failure in {
            EditFailureType.STALE_CONTEXT,
            EditFailureType.AMBIGUOUS_MATCH,
            EditFailureType.INVALID_RANGE,
        } and path:
            if self.pending is not None and self.pending.read_completed:
                self.pending = None
                return (
                    "唯一的过期上下文编辑重试也失败了。请勿循环；"
                    "报告具体冲突，或选择另一条有证据的编辑路径。"
                )
            self.pending = PendingEditRetry(
                path=path,
                edit_tool=tool_name,
                start_line=self._optional_int(result.data.get("start_line")),
                end_line=self._optional_int(result.data.get("end_line")),
                failure_type=typed_failure,
            )
            return self.read_instruction()

        if tool_name == "replace_symbol" and typed_failure == EditFailureType.SYMBOL_NOT_FOUND:
            self.pending = PendingEditRetry(
                path=path,
                edit_tool=tool_name,
                failure_type=typed_failure,
                symbol=str(result.data.get("symbol", arguments.get("symbol", "")) or ""),
            )
            return self.read_instruction()

        if typed_failure == EditFailureType.NO_CHANGE:
            return (
                "该编辑不会产生任何变更。请检查当前证据，"
                "并确认请求的状态是否已经满足。"
            )

        if typed_failure == EditFailureType.PERMISSION_DENIED:
            return "BLOCKED: 编辑请求路径时权限被拒绝"

        pending = self.pending
        if pending is None:
            return None
        if (
            pending.failure_type == EditFailureType.SYMBOL_NOT_FOUND
            and tool_name == "search_symbol"
            and result.success
        ):
            pending.read_completed = True
            return "符号搜索已完成。请用更精确的范围重试一次 replace_symbol。"
        if tool_name == "read_file" and path == pending.path and result.success:
            pending.read_completed = True
            return (
                f"{pending.path} 中的受影响源码已是最新。"
                f"请基于当前内容重试一次 {pending.edit_tool} 编辑。"
            )
        if tool_name in EDIT_TOOLS and path == pending.path:
            pending.retry_used = True
            self.pending = None
        return None

    def read_instruction(self) -> str:
        pending = self.pending
        if pending is None:
            return ""
        if pending.failure_type == EditFailureType.SYMBOL_NOT_FOUND:
            return (
                f"未找到符号 {pending.symbol or '<unknown>'!r}。"
                "请先调用一次 search_symbol，再用更精确的范围重试一次 replace_symbol。"
            )
        range_text = ""
        if pending.start_line is not None:
            end = pending.end_line or pending.start_line
            range_text = f" 第 {pending.start_line}-{end} 行附近"
        return (
            f"编辑被拒绝（{pending.failure_type.value}）。请先读取 "
            f"{pending.path}{range_text} 一次，再重试一次定向编辑。"
            "请勿扩大搜索或重新规划。"
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
