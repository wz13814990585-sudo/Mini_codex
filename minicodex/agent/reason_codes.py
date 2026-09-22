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
    PERMISSION_DENIED = "permission_denied"
    DUPLICATE_TOOL_CALL = "duplicate_tool_call"
    VALIDATION_TARGET_MISMATCH = "validation_target_mismatch"
    PLAN_INCOMPLETE = "plan_incomplete"
    DEPENDENCY_MANIFEST_REQUIRED = "dependency_manifest_required"
    MAX_STEPS = "max_steps"
    BLOCKED = "blocked"


_DISPLAY_LABELS: dict[ReasonCode, str] = {
    ReasonCode.INSPECTION_LIMIT: "已达到检查次数上限",
    ReasonCode.STALE_CONTEXT: "上下文已过期",
    ReasonCode.AMBIGUOUS_MATCH: "匹配结果不唯一",
    ReasonCode.SYMBOL_NOT_FOUND: "未找到符号",
    ReasonCode.INVALID_RANGE: "范围无效",
    ReasonCode.ACCEPTANCE_MISSING: "缺少验收证据",
    ReasonCode.REGRESSION_MISSING: "缺少回归证据",
    ReasonCode.FULL_REGRESSION_MISSING: "缺少完整回归证据",
    ReasonCode.UNSAFE_COMMAND: "命令不安全",
    ReasonCode.PERMISSION_DENIED: "用户拒绝了操作权限",
    ReasonCode.DUPLICATE_TOOL_CALL: "重复的工具调用",
    ReasonCode.VALIDATION_TARGET_MISMATCH: "验证目标与当前契约不匹配",
    ReasonCode.PLAN_INCOMPLETE: "计划未完成",
    ReasonCode.DEPENDENCY_MANIFEST_REQUIRED: "需要先更新依赖清单",
    ReasonCode.MAX_STEPS: "已达到最大 Agent 步数",
    ReasonCode.BLOCKED: "任务已阻塞",
}


def reason_value(reason: ReasonCode | str | None) -> str | None:
    if reason is None:
        return None
    return reason.value if isinstance(reason, ReasonCode) else str(reason)


def display_label(reason: ReasonCode | str | None) -> str | None:
    """Chinese display label for a ReasonCode; enum values stay English."""
    if reason is None:
        return None
    if isinstance(reason, ReasonCode):
        return _DISPLAY_LABELS.get(reason, reason.value)
    try:
        code = ReasonCode(str(reason))
    except ValueError:
        return str(reason)
    return _DISPLAY_LABELS.get(code, code.value)
