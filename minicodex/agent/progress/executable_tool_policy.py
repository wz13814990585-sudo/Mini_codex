"""Shared executable-tool policy for schema filtering and ActionController.

Schema exposure and runtime guards must derive from the same machine state so
Advertised Action Space ⊆ Executable Action Space.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..task_state import AgentPhase


# Registry-facing capability atoms (source of truth in ToolRegistry).
CAP_FILE_READ = "filesystem.read"
CAP_FILE_READ_ALIAS = "file.read"
CAP_CODE_SEARCH = "code.search"
CAP_CODE_EDIT = "code.edit"
CAP_TEST_RUN = "test.run"
CAP_PROCESS_RUN = "process.run"
CAP_VALIDATION_STATIC_WEB = "validation.static_web"
CAP_VALIDATION_BROWSER = "validation.browser"
CAP_SERVICE_VALIDATE = "service.validate"
CAP_GIT_INSPECT = "git.inspect"
CAP_PLAN_CONTROL = "plan.control"
CAP_DEPENDENCY_INSTALL = "dependency.install"
CAP_VALIDATION_SEMANTIC = "validation.semantic"

INSPECTION_CAPABILITIES = frozenset(
    {CAP_FILE_READ, CAP_FILE_READ_ALIAS, CAP_CODE_SEARCH, CAP_GIT_INSPECT}
)
EDIT_CAPABILITIES = frozenset({CAP_CODE_EDIT})
VALIDATION_CAPABILITIES = frozenset(
    {
        CAP_TEST_RUN,
        CAP_PROCESS_RUN,
        CAP_VALIDATION_STATIC_WEB,
        CAP_VALIDATION_BROWSER,
        CAP_SERVICE_VALIDATE,
    }
)

CONTRACT_VALIDATION_CAPABILITIES: dict[str, frozenset[str]] = {
    "browser_interaction": frozenset({CAP_VALIDATION_BROWSER}),
    "python_behavior": frozenset({CAP_PROCESS_RUN}),
    "node_behavior": frozenset({CAP_PROCESS_RUN}),
    "pytest": frozenset({CAP_TEST_RUN}),
    "http_response": frozenset({CAP_SERVICE_VALIDATE}),
    "file_contains": frozenset({CAP_PROCESS_RUN, CAP_TEST_RUN}),
    "file_exists": frozenset({CAP_PROCESS_RUN, CAP_TEST_RUN}),
    "command": frozenset({CAP_PROCESS_RUN}),
}

NON_HTTP_CONTRACTS = frozenset(
    {
        "python_behavior",
        "node_behavior",
        "pytest",
        "file_contains",
        "file_exists",
        "command",
    }
)


class SchemaDenialReason(str, Enum):
    PHASE_INSPECTION_BLOCKED = "phase_inspection_blocked"
    ACTION_REQUIRED = "action_required"
    FIXING_SEARCH_BLOCKED = "fixing_search_blocked"
    FIXING_READ_BUDGET = "fixing_read_budget"
    VALIDATING_INSPECTION_BUDGET = "validating_inspection_budget"
    FINALIZATION_RECON = "finalization_recon"
    CONTRACT_VALIDATOR_MISMATCH = "contract_validator_mismatch"
    VALIDATION_MILESTONE = "validation_milestone"
    EDIT_RETRY_REFRESH = "edit_retry_refresh"


# Keep in sync with tools.editing / EditRetryPolicy.EDIT_TOOLS.
EDIT_TOOL_NAMES = frozenset(
    {"write_file", "patch_file", "replace_lines", "replace_symbol"}
)

VALIDATION_MILESTONE_MESSAGE = (
    "The bounded edit unit requires validation before further edits."
)


@dataclass(frozen=True)
class ExecutableToolPolicyState:
    """Deterministic snapshot used by both schema resolver and runtime guard."""

    phase: AgentPhase = AgentPhase.INSPECTING
    action_required: bool = False
    consecutive_inspections: int = 0
    validation_inspections: int = 0
    inspection_budget: int | None = None
    unresolved_inspection_limit: int = 1
    next_contract_type: str = ""
    next_required_check_id: str = ""
    validator_resolution_status: str = ""
    validation_paths: tuple[str, ...] = ()
    target_paths: tuple[str, ...] = ()
    has_edit: bool = False
    finalization_active: bool = False
    allow_proof_inspection: bool = False
    enable_replan: bool = False
    exposed_tool_names: frozenset[str] | None = None
    denied_tool_names: frozenset[str] = field(default_factory=frozenset)
    # WorkUnit.milestone_due — must match tool_batch validation_milestone guard.
    milestone_due: bool = False
    # EditRetryPolicy pending refresh — allow one targeted read even under
    # action_required so schema and runtime cannot deadlock.
    edit_retry_needs_read: bool = False
    edit_retry_path: str = ""


@dataclass(frozen=True)
class ExecutableToolDecision:
    allowed_capabilities: frozenset[str]
    denied_tool_names: frozenset[str] = field(default_factory=frozenset)
    denial_reasons: tuple[str, ...] = ()


def _inspection_budget(state: ExecutableToolPolicyState) -> int | None:
    if state.inspection_budget is not None:
        return state.inspection_budget
    if state.phase == AgentPhase.INSPECTING:
        return 3
    if state.phase in {AgentPhase.ACTING, AgentPhase.FIXING}:
        return 1
    if state.phase in {AgentPhase.VALIDATING, AgentPhase.FINALIZING}:
        if state.validator_resolution_status == "target_unresolved":
            return state.unresolved_inspection_limit
        return 0
    return None


def contract_validation_capabilities(contract_type: str) -> frozenset[str]:
    contract = str(contract_type or "").strip()
    if not contract:
        return frozenset(VALIDATION_CAPABILITIES)
    preferred = CONTRACT_VALIDATION_CAPABILITIES.get(contract)
    if preferred is not None:
        return preferred
    return frozenset(VALIDATION_CAPABILITIES)


def is_inspection_capability(capabilities: frozenset[str] | set[str]) -> bool:
    return bool(frozenset(capabilities) & INSPECTION_CAPABILITIES)


def is_read_capability(capabilities: frozenset[str] | set[str]) -> bool:
    """Targeted file read only — matches ActionController ``file.read``.

    ``filesystem.read`` alone (e.g. ``list_files``) is broad inspection, not a
    targeted read, and must not share the FIXING one-read grant.
    """

    return CAP_FILE_READ_ALIAS in frozenset(capabilities)


def is_broad_filesystem_inspection(capabilities: frozenset[str] | set[str]) -> bool:
    """True for list/dir style tools that lack targeted ``file.read``."""

    caps = frozenset(capabilities)
    return CAP_FILE_READ in caps and CAP_FILE_READ_ALIAS not in caps


def is_search_capability(capabilities: frozenset[str] | set[str]) -> bool:
    return CAP_CODE_SEARCH in capabilities


class ExecutableToolPolicy:
    """Pure policy: given state (+ optional tool caps), decide allow / deny."""

    @staticmethod
    def resolve(state: ExecutableToolPolicyState) -> ExecutableToolDecision:
        """Compute advertised capabilities for the current runtime state."""

        denials: list[str] = []
        denied_tools = set(state.denied_tool_names)

        allowed: set[str] = set(EDIT_CAPABILITIES)
        allowed.add(CAP_DEPENDENCY_INSTALL)
        allowed.add(CAP_VALIDATION_SEMANTIC)
        allowed |= set(contract_validation_capabilities(state.next_contract_type))

        if state.next_contract_type in NON_HTTP_CONTRACTS:
            denied_tools.add("validate_service")
            denials.append(SchemaDenialReason.CONTRACT_VALIDATOR_MISMATCH.value)
        if state.next_contract_type == "browser_interaction":
            denied_tools.add("validate_static_web")
            denials.append(SchemaDenialReason.CONTRACT_VALIDATOR_MISMATCH.value)

        if state.enable_replan:
            allowed.add(CAP_PLAN_CONTROL)

        budget = _inspection_budget(state)
        allow_inspection = True

        if state.edit_retry_needs_read:
            # Stale-edit recovery must be able to refresh even under
            # action_required / finalization recon lockdown.
            allow_inspection = True
        elif state.action_required:
            # FIXING still permits one targeted read before the action gate
            # fully closes reconnaissance (matches ActionController order).
            if state.phase == AgentPhase.FIXING and state.consecutive_inspections < 1:
                allow_inspection = True
            else:
                allow_inspection = False
                denials.append(SchemaDenialReason.ACTION_REQUIRED.value)
        elif state.finalization_active and not state.allow_proof_inspection:
            allow_inspection = False
            denials.append(SchemaDenialReason.FINALIZATION_RECON.value)
            denied_tools.update(
                {
                    "read_file",
                    "search_code",
                    "search_symbol",
                    "list_files",
                    "git_status",
                    "git_diff",
                }
            )
        elif state.phase in {AgentPhase.VALIDATING, AgentPhase.FINALIZING}:
            status = state.validator_resolution_status
            if status == "target_unresolved":
                if state.validation_inspections >= state.unresolved_inspection_limit:
                    allow_inspection = False
                    denials.append(SchemaDenialReason.VALIDATING_INSPECTION_BUDGET.value)
                else:
                    allow_inspection = True
            elif status in {"capability_missing", "unsupported"}:
                allow_inspection = False
                denials.append(SchemaDenialReason.PHASE_INSPECTION_BLOCKED.value)
            else:
                allow_inspection = False
                denials.append(SchemaDenialReason.PHASE_INSPECTION_BLOCKED.value)
        elif state.phase == AgentPhase.FIXING:
            allowed.discard(CAP_CODE_SEARCH)
            allowed.discard(CAP_GIT_INSPECT)
            # Broad filesystem listing is never the FIXING one-read grant.
            denied_tools.add("list_files")
            denials.append(SchemaDenialReason.FIXING_SEARCH_BLOCKED.value)
            if state.consecutive_inspections >= 1:
                allow_inspection = False
                denials.append(SchemaDenialReason.FIXING_READ_BUDGET.value)
            else:
                allow_inspection = True
                # Targeted read only (file.read / read_file). Do not advertise
                # bare filesystem.read — that exposes list_files and breaks
                # Advertised ⊆ Executable with ActionController.
                allowed.add(CAP_FILE_READ_ALIAS)
        elif state.phase == AgentPhase.INSPECTING:
            allow_inspection = True
            if budget is not None and state.consecutive_inspections >= budget:
                allow_inspection = False
                denials.append(SchemaDenialReason.ACTION_REQUIRED.value)
        elif state.phase == AgentPhase.ACTING:
            if budget is not None and state.consecutive_inspections >= budget:
                allow_inspection = False
                denials.append(SchemaDenialReason.ACTION_REQUIRED.value)
            else:
                allow_inspection = True

        if allow_inspection and state.phase != AgentPhase.FIXING and not state.edit_retry_needs_read:
            allowed.update(INSPECTION_CAPABILITIES)
        elif allow_inspection and state.phase == AgentPhase.FIXING and not state.edit_retry_needs_read:
            allowed.add(CAP_FILE_READ_ALIAS)
            denied_tools.add("list_files")
        elif allow_inspection and state.edit_retry_needs_read:
            # Only the pending-path refresh read — not list/search/git.
            allowed.add(CAP_FILE_READ_ALIAS)
            denied_tools.update(
                {"list_files", "search_code", "search_symbol", "git_status", "git_diff"}
            )

        # Bounded edit unit: further code.edit is rejected until validation runs.
        # Must stay aligned with tool_batch.resolve_tool_restriction.
        if state.milestone_due:
            allowed.difference_update(EDIT_CAPABILITIES)
            denied_tools.update(EDIT_TOOL_NAMES)
            denials.append(SchemaDenialReason.VALIDATION_MILESTONE.value)

        # Stale-context recovery: hide edits until the required refresh read.
        if state.edit_retry_needs_read:
            allowed.difference_update(EDIT_CAPABILITIES)
            denied_tools.update(EDIT_TOOL_NAMES)
            denials.append(SchemaDenialReason.EDIT_RETRY_REFRESH.value)

        return ExecutableToolDecision(
            allowed_capabilities=frozenset(allowed),
            denied_tool_names=frozenset(denied_tools),
            denial_reasons=tuple(dict.fromkeys(denials)),
        )

    @classmethod
    def capability_block_reason(
        cls,
        state: ExecutableToolPolicyState,
        *,
        tool_name: str,
        capabilities: frozenset[str] | set[str],
    ) -> str | None:
        """Return a stable reason when a tool is capability-blocked (no args).

        Argument-specific checks (wrong path, content shape) stay in
        ActionController and are intentionally outside schema filtering.
        """

        decision = cls.resolve(state)
        caps = frozenset(capabilities)

        if CAP_CODE_EDIT in caps and state.milestone_due:
            return VALIDATION_MILESTONE_MESSAGE
        if CAP_CODE_EDIT in caps and state.edit_retry_needs_read:
            path = state.edit_retry_path or "目标文件"
            return (
                f"上次编辑使用了过期上下文。请先只读取 {path} "
                f"的受影响区域，再重试编辑。"
            )

        if tool_name in decision.denied_tool_names:
            if tool_name == "list_files" and state.phase == AgentPhase.FIXING:
                return (
                    "验证失败。最多探查一个针对性源码区域，然后修复。"
                    "不允许大范围侦察。"
                )
            if state.milestone_due and tool_name in EDIT_TOOL_NAMES:
                return VALIDATION_MILESTONE_MESSAGE
            if tool_name == "validate_static_web" and state.next_contract_type == "browser_interaction":
                return (
                    f"当前必需检查 {state.next_required_check_id or 'browser_interaction'} "
                    "是浏览器交互契约。请修复 HTML 引用的脚本中的事件监听，"
                    "不要用 validate_static_web / require_inline_script 替代。"
                )
            if tool_name == "validate_service" and state.next_contract_type in NON_HTTP_CONTRACTS:
                return (
                    f"当前必需检查 {state.next_required_check_id or 'current'} 的契约是 "
                    f"{state.next_contract_type}，不是 HTTP 服务。"
                    "请修复实现使原 python/文件验收通过；"
                    "不要用 validate_service 或 Web endpoint 替代该契约。"
                )
            return (
                f"工具 '{tool_name}' 与当前验收契约不匹配，"
                "请使用契约要求的验证能力。"
            )

        if is_inspection_capability(caps):
            if not (caps & decision.allowed_capabilities & INSPECTION_CAPABILITIES):
                if (
                    state.action_required
                    and not (
                        (
                            state.phase == AgentPhase.FIXING
                            and state.consecutive_inspections < 1
                            and is_read_capability(caps)
                        )
                        or (state.edit_retry_needs_read and is_read_capability(caps))
                    )
                ):
                    return (
                        "上下文已足够。请做一次具体编辑、运行所需验证，"
                        "或报告一个具体阻塞原因。"
                    )
                if state.finalization_active and not state.allow_proof_inspection:
                    return (
                        "因任务预算偏低，已进入收尾模式。"
                        "不要把剩余步骤花在侦察上。"
                    )
                if state.phase in {AgentPhase.VALIDATING, AgentPhase.FINALIZING}:
                    return (
                        "当前修订已有可执行的验证目标。请运行相关验证器，"
                        "不要做无关探查。"
                    )
                if state.phase == AgentPhase.FIXING and (
                    is_search_capability(caps) or is_broad_filesystem_inspection(caps)
                ):
                    return (
                        "验证失败。最多探查一个针对性源码区域，然后修复。"
                        "不允许大范围侦察。"
                    )
                if state.phase == AgentPhase.FIXING and is_read_capability(caps):
                    return (
                        "针对性失败上下文已探查过。"
                        "请用 write_file/patch_file 做具体修复，或报告阻塞原因。"
                    )
                return "当前阶段不允许继续侦察类工具。"

        if CAP_SERVICE_VALIDATE in caps and state.next_contract_type in NON_HTTP_CONTRACTS:
            return (
                f"当前必需检查 {state.next_required_check_id or 'current'} 的契约是 "
                f"{state.next_contract_type}，不是 HTTP 服务。"
            )
        if (
            CAP_VALIDATION_STATIC_WEB in caps
            and state.next_contract_type == "browser_interaction"
        ):
            return (
                f"当前必需检查 {state.next_required_check_id or 'browser_interaction'} "
                "是浏览器交互契约；不要用 validate_static_web 替代。"
            )

        return None
