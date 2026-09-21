"""One deterministic source of truth for action/progress pressure."""

from __future__ import annotations

import re

from ..task_state import AgentPhase, TaskState
from .progress import ProgressKind, ProgressSignal


class ActionController:
    """Bound reconnaissance without confusing observations with progress.

    The controller never mutates provider messages and never executes tools.
    It only observes deterministic task state and decides when ordinary
    reconnaissance must yield to edit, validation, plan progress, or a
    concrete blocker.
    """

    INSTRUCTION = (
        "上下文已足够。请做一次具体编辑、运行所需验证，或报告一个具体阻塞原因。"
    )
    UNRESOLVED_INSPECTION_LIMIT = 1

    @staticmethod
    def _normalize_path(path: str) -> str:
        raw = str(path or "").strip().replace("\\", "/")
        while raw.startswith("./"):
            raw = raw[2:]
        return raw.strip("/")

    def allowed_edit_paths(self) -> tuple[str, ...]:
        """Deterministic edit targets from the current obligation / task paths."""

        paths = tuple(
            dict.fromkeys(
                self._normalize_path(path)
                for path in (self.validation_paths or self.target_paths or ())
                if self._normalize_path(path)
            )
        )
        return paths

    def force_edit_instruction(self) -> str:
        """Path-named instruction used when the model replies without tools."""

        paths = self.allowed_edit_paths()
        if paths:
            create_hint = ""
            if self.next_contract_type in {"file_contains", "file_exists"} or not self.has_edit:
                create_hint = (
                    "若某目标路径尚不存在，先用 write_file 创建并写入所需定义；"
                )
            return (
                f"不要只回复文字。请立刻用 write_file/patch_file 修改这些验收路径："
                f"{', '.join(paths)}。"
                f"{create_hint}"
                "改完后立即再跑同一验收命令。"
            )
        return (
            "不要只回复文字。请立刻用 write_file/patch_file 做具体代码修改，"
            "然后运行验收；禁止空回复。"
        )

    def __init__(self, registry=None) -> None:
        self.registry = registry
        self.reset()

    def _capabilities(self, name):
        from ...tools.registry import ToolRegistry
        if self.registry is not None and name in getattr(self.registry, "_tools", {}):
            return self.registry.capabilities_for(name)
        return frozenset(ToolRegistry._LEGACY_CAPABILITIES.get(name, ()))

    def _inspection(self, name):
        return bool(self._capabilities(name) & {"filesystem.read", "code.search", "git.inspect"})

    def reset(self, state: TaskState | None = None) -> None:
        self.last_state = state
        self.last_progress_key = state.progress_key() if state is not None else None
        self.consecutive_inspections = 0
        self.consecutive_no_state_change = 0
        self.action_required = False
        self.action_required_trigger_count = 0
        self.has_edit = bool(state and state.edit_revision > 0)
        self.acceptance_missing = True
        self.next_required_check_id = ""
        self.next_contract_type = ""
        self.validator_resolution_status = ""
        self.unresolved_reason = ""
        self.validation_paths = ()
        self.validation_inspections = 0
        self.current_mode = None
        self.remaining_budget: int | None = None
        self.phase = getattr(state, "phase", AgentPhase.INSPECTING)
        self.target_paths = tuple(
            getattr(state, "relevant_paths", ())
            or getattr(state, "target_paths", ())
            or ()
        )
        self.baseline_web_framework = ""

    def update_context(
        self,
        *,
        state: TaskState,
        policy,
        remaining_budget: int,
        acceptance_missing: bool | None = None,
        next_required_check_id: str = "",
        next_contract_type: str = "",
        validator_resolution_status: object = "",
        unresolved_reason: str = "",
        validation_paths=(),
        baseline_web_framework: str | None = None,
    ) -> None:
        """Expose current deterministic task context without adding pressure."""

        if self.last_state is None:
            self.last_state = state
        if self.last_progress_key is None:
            self.last_progress_key = state.progress_key()
        self.has_edit = state.edit_revision > 0
        # This is retained only for UI/legacy callers. A materialized plan is
        # represented below by its exact next required check.
        if acceptance_missing is not None:
            self.acceptance_missing = bool(acceptance_missing)
        elif next_required_check_id:
            self.acceptance_missing = True
        self.current_mode = getattr(policy, "mode", None)
        self.remaining_budget = max(0, int(remaining_budget))
        self.phase = state.phase
        self.target_paths = state.relevant_paths or state.target_paths
        status = getattr(validator_resolution_status, "value", validator_resolution_status)
        same_obligation = (next_required_check_id == self.next_required_check_id
                           and status == self.validator_resolution_status)
        self.next_required_check_id = str(next_required_check_id or "")
        self.next_contract_type = str(next_contract_type or "")
        self.validator_resolution_status = str(status or "")
        self.unresolved_reason = str(unresolved_reason or "")
        self.validation_paths = tuple(dict.fromkeys(validation_paths or self.target_paths))
        if baseline_web_framework is not None:
            self.baseline_web_framework = str(baseline_web_framework or "")
        if not same_obligation:
            self.validation_inspections = 0

    def observe_action(
        self,
        tool_name: str,
        state: TaskState,
        signal: ProgressSignal,
    ) -> bool:
        """Record one action and return whether it genuinely advanced work."""

        current_key = state.progress_key()
        self.last_state = state
        self.last_progress_key = current_key
        self.has_edit = state.edit_revision > 0

        if signal.kind == ProgressKind.ADVANCED:
            self.consecutive_inspections = 0
            self.consecutive_no_state_change = 0
            self.action_required = False
            return True

        self.consecutive_no_state_change += 1
        if self._inspection(tool_name):
            self.consecutive_inspections += 1
        else:
            self.consecutive_inspections = 0
        return False

    def update_pressure(self, policy) -> bool:
        inspection_limit = self._inspection_limit(policy)
        no_change_limit = getattr(policy, "max_no_progress_steps", None)
        should_require = bool(
            (
                inspection_limit is not None
                and self.consecutive_inspections >= inspection_limit
            )
            or (
                no_change_limit is not None
                and self.consecutive_no_state_change >= no_change_limit
            )
        )
        if should_require and not self.action_required:
            self.action_required = True
            self.action_required_trigger_count += 1
            return True
        return False

    def executable_policy_state(
        self,
        policy,
        *,
        finalization_active: bool = False,
        allow_proof_inspection: bool = False,
    ) -> "ExecutableToolPolicyState":
        """Snapshot shared with ToolAvailabilityResolver / schema filtering."""

        from .executable_tool_policy import ExecutableToolPolicyState

        return ExecutableToolPolicyState(
            phase=self.phase,
            action_required=bool(self.action_required),
            consecutive_inspections=int(self.consecutive_inspections or 0),
            validation_inspections=int(self.validation_inspections or 0),
            inspection_budget=self._inspection_limit(policy),
            unresolved_inspection_limit=int(self.UNRESOLVED_INSPECTION_LIMIT),
            next_contract_type=str(self.next_contract_type or ""),
            next_required_check_id=str(self.next_required_check_id or ""),
            validator_resolution_status=str(self.validator_resolution_status or ""),
            validation_paths=tuple(self.validation_paths or ()),
            target_paths=tuple(self.target_paths or ()),
            has_edit=bool(self.has_edit),
            finalization_active=bool(finalization_active),
            allow_proof_inspection=bool(allow_proof_inspection),
            enable_replan=bool(getattr(policy, "enable_replan", False)),
            exposed_tool_names=(
                frozenset(getattr(policy, "exposed_tool_names"))
                if getattr(policy, "exposed_tool_names", None) is not None
                else None
            ),
        )

    def restriction_reason(
        self,
        tool_name: str,
        arguments: dict | None,
        policy,
        *,
        finalization_active: bool = False,
        allow_proof_inspection: bool = False,
    ) -> str | None:
        """Block only another wasteful action; edits/validation stay open."""

        self.current_mode = getattr(policy, "mode", None)
        capabilities = self._capabilities(tool_name)
        is_read = "file.read" in capabilities

        # Align with schema filtering for argument-independent capability blocks.
        # Unresolved validation still needs the path-scoped grant + counter below.
        from .executable_tool_policy import ExecutableToolPolicy
        skip_shared = (
            self.phase in {AgentPhase.VALIDATING, AgentPhase.FINALIZING}
            and self.validator_resolution_status == "target_unresolved"
            and self._inspection(tool_name)
        )
        if not skip_shared:
            shared_reason = ExecutableToolPolicy.capability_block_reason(
                self.executable_policy_state(
                    policy,
                    finalization_active=finalization_active,
                    allow_proof_inspection=allow_proof_inspection,
                ),
                tool_name=tool_name,
                capabilities=capabilities,
            )
            if shared_reason:
                # Match legacy pressure: only INSPECTING/ACTING budget gates
                # flip action_required. FIXING/VALIDATING denials stay local.
                if self._inspection(tool_name) and self.phase in {
                    AgentPhase.INSPECTING,
                    AgentPhase.ACTING,
                }:
                    self._activate()
                return shared_reason

        if self.phase in {AgentPhase.VALIDATING, AgentPhase.FINALIZING} and self._inspection(tool_name):
            if self.validator_resolution_status == "target_unresolved":
                if self.validation_inspections >= self.UNRESOLVED_INSPECTION_LIMIT:
                    self._activate()
                    return (
                        f"验证检查 {self.next_required_check_id or 'current'} 在一次针对性探查后仍未解析。"
                        "请重新绑定、解析能力，或报告具体阻塞原因。"
                    )
                path = str((arguments or {}).get("path", "") or "").strip()
                if path and self.validation_paths and path not in self.validation_paths:
                    return (
                        f"仅允许针对 {self.next_required_check_id or '当前检查'} 的证据导向探查"
                        f"（{', '.join(self.validation_paths)}），不允许探查 {path}。"
                    )
                # The restriction boundary is invoked exactly once per tool
                # call. Count the granted inspection here so a model cannot
                # turn unresolved binding into open-ended reconnaissance.
                self.validation_inspections += 1
                return None
            if self.validator_resolution_status in {"capability_missing", "unsupported"}:
                return (
                    f"验证检查 {self.next_required_check_id or 'current'} 状态为 "
                    f"{self.validator_resolution_status}；源码探查无法解决该环境/阻塞状态。"
                )
            return (
                "当前修订已有可执行的验证目标。请运行相关验证器，"
                "不要做无关探查。"
            )
        if self.phase == AgentPhase.FIXING:
            if self._inspection(tool_name) and not is_read:
                return (
                    "验证失败。最多探查一个针对性源码区域，然后修复。"
                    "不允许大范围侦察。"
                )
            if is_read and self.consecutive_inspections >= 1:
                if self.next_contract_type in {"file_contains", "file_exists"}:
                    return (
                        "目标结构文件可能尚不存在。"
                        "请立即用 write_file 创建缺失路径并写入所需定义，"
                        "不要继续 read/search。"
                    )
                return (
                    "针对性失败上下文已探查过。"
                    "请用 write_file/patch_file 做具体修复（若目标文件不存在请先创建），"
                    "或报告阻塞原因。"
                )
            if is_read and self.target_paths:
                path = str((arguments or {}).get("path", "") or "").strip()
                if path not in self.target_paths:
                    return (
                        "FIXING 阶段仅允许读取一个相关失败路径"
                        f"（{', '.join(self.target_paths)}），不允许 {path or '未指定路径'}。"
                    )

        # Pin edits to the current obligation paths so models cannot invent
        # parallel modules (e.g. login.py) while acceptance imports app.py.
        if capabilities & {"code.edit"}:
            allowed = self.allowed_edit_paths()
            if allowed:
                path = self._normalize_path(str((arguments or {}).get("path", "") or ""))
                if path and path not in allowed:
                    return (
                        f"当前验收路径为 {', '.join(allowed)}。"
                        f"请编辑这些文件，不要写入 {path}。"
                    )
            edit_block = self._edit_content_restriction(tool_name, arguments or {})
            if edit_block:
                return edit_block

        if tool_name == "replan" and not getattr(policy, "enable_replan", False):
            return "FAST 模式无计划；replan 不可用。"

        if (
            tool_name == "validate_static_web"
            and self.next_contract_type == "browser_interaction"
        ):
            return (
                f"当前必需检查 {self.next_required_check_id or 'browser_interaction'} "
                "是浏览器交互契约。请修复 HTML 引用的脚本中的事件监听，"
                "不要用 validate_static_web / require_inline_script 替代。"
            )

        # Required contract is source of truth: do not chase workspace-shaped HTTP
        # validators when acceptance is a plain python_behavior/pytest check.
        if (
            tool_name == "validate_service"
            or "service.validate" in capabilities
        ) and self.next_contract_type in {
            "python_behavior",
            "node_behavior",
            "pytest",
            "file_contains",
            "file_exists",
            "command",
        }:
            return (
                f"当前必需检查 {self.next_required_check_id or 'current'} 的契约是 "
                f"{self.next_contract_type}，不是 HTTP 服务。"
                "请修复实现使原 python/文件验收通过；"
                "不要用 validate_service 或 Web endpoint 替代该契约。"
            )

        if (
            "test.run" in capabilities
            and str((arguments or {}).get("purpose", "regression")).lower()
            == "regression"
            and str((arguments or {}).get("path", ".")).strip() in {"", ".", "./"}
            and str(
                getattr(
                    getattr(policy, "regression_requirement", None),
                    "value",
                    "",
                )
            ) == "not_applicable"
        ):
            return (
                "全仓库回归不适用于此隔离 FAST 任务。"
                "请改为运行一次针对性验收验证。"
            )

        inspection_limit = self._inspection_limit(policy)
        next_inspection_exceeds_budget = bool(
            inspection_limit is not None
            and self._inspection(tool_name)
            and self.consecutive_inspections >= inspection_limit
        )
        if next_inspection_exceeds_budget:
            self._activate()

        if not self.action_required:
            return None

        if capabilities & {"code.edit", "test.run", "validation.static_web", "validation.browser", "service.validate"}:
            return None
        if "process.run" in capabilities and str(
            (arguments or {}).get("purpose", "diagnostic")
        ).strip().lower() in {"acceptance", "regression"}:
            return None
        if tool_name == "replan" and getattr(policy, "enable_replan", False):
            return None
        if self._inspection(tool_name) or "process.run" in capabilities:
            return self.INSTRUCTION
        return None

    def _edit_content_restriction(self, tool_name: str, arguments: dict) -> str | None:
        path = self._normalize_path(str(arguments.get("path", "") or ""))
        content = str(
            arguments.get("content")
            or arguments.get("new_text")
            or arguments.get("new_content")
            or ""
        )
        if not content:
            return None

        if path.endswith((".ts", ".tsx")) and self._has_typescript_type_annotations(content):
            return (
                "TypeScript 验收按 data:text/javascript 加载（与隐藏 oracle 一致），"
                "禁止类型注解。请写出无 `: number` / `: string` 等注解的模块风格代码。"
            )

        if (
            tool_name == "write_file"
            and self.next_contract_type == "python_behavior"
            and re.search(r"\bFlask\b|\bFastAPI\b|@app\.(route|get|post)\b", content)
        ):
            return (
                "当前必需检查是 python_behavior。"
                "请用 patch_file 在现有 public callable 上做增量修改，"
                "不要把实现重写成 Flask/FastAPI Web endpoint。"
            )

        baseline = str(self.baseline_web_framework or "")
        if path.endswith("app.py") and baseline in {"fastapi", "flask"}:
            lowered = content.casefold()
            if baseline == "fastapi":
                if "fastapi" not in lowered or re.search(
                    r"\bflask\b|http\.server|basehttprequesthandler", lowered
                ):
                    return (
                        "仓库基线是 FastAPI。"
                        "请用 patch_file 增量修改现有 FastAPI app（例如补 status_code / Email 校验），"
                        "不要改成 Flask 或 http.server。"
                    )
            if baseline == "flask":
                if "flask" not in lowered or re.search(
                    r"\bfastapi\b|http\.server|basehttprequesthandler", lowered
                ):
                    return (
                        "仓库基线是 Flask。"
                        "请用 patch_file 增量修改现有 Flask app，"
                        "不要改成 FastAPI 或 http.server。"
                    )
        return None

    @staticmethod
    def _has_typescript_type_annotations(content: str) -> bool:
        return bool(
            re.search(
                r":\s*(number|string|boolean|any|void|unknown|never|bigint)\b|"
                r":\s*[A-Za-z_][\w.]*(\[\])?(\s*\|\s*[A-Za-z_][\w.]*)*\s*[=,)\n]|"
                r"\)\s*:\s*[A-Za-z_\[\]|<]",
                content,
            )
        )

    def _activate(self) -> None:
        if not self.action_required:
            self.action_required = True
            self.action_required_trigger_count += 1

    def _inspection_limit(self, policy) -> int | None:
        configured = getattr(policy, "max_inspection_calls", None)
        if self.phase == AgentPhase.INSPECTING:
            return min(configured, 3) if configured is not None else 3
        if self.phase in {AgentPhase.ACTING, AgentPhase.FIXING}:
            return 1
        if self.phase in {AgentPhase.VALIDATING, AgentPhase.FINALIZING}:
            if self.validator_resolution_status == "target_unresolved":
                return self.UNRESOLVED_INSPECTION_LIMIT
            return 0
        return configured
    # Kept as compatibility-facing classification constants for metrics. Core
    # control decisions below use registry capabilities instead.
    INSPECTION_TOOLS = frozenset({"read_file", "search_code", "search_symbol", "list_files", "git_status", "git_diff"})
    EDIT_TOOLS = frozenset({"write_file", "patch_file", "replace_lines", "replace_symbol"})
    VALIDATION_TOOLS = frozenset({"validate_static_web", "validate_browser_app", "run_tests"})
