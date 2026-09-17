"""One deterministic source of truth for action/progress pressure."""

from __future__ import annotations

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
        "You have enough context. Make a concrete edit, run the required "
        "validation, or report a concrete blocker."
    )
    UNRESOLVED_INSPECTION_LIMIT = 1

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

    def update_context(
        self,
        *,
        state: TaskState,
        policy,
        remaining_budget: int,
        acceptance_missing: bool | None = None,
        next_required_check_id: str = "",
        validator_resolution_status: object = "",
        unresolved_reason: str = "",
        validation_paths=(),
    ) -> None:
        """Expose current deterministic task context without adding pressure."""

        if self.last_state is None:
            self.last_state = state
        if self.last_progress_key is None:
            self.last_progress_key = state.progress_key()
        self.has_edit = state.edit_revision > 0
        # This is retained only for UI/legacy callers. A materialized plan is
        # represented below by its exact next required check.
        self.acceptance_missing = bool(acceptance_missing)
        self.current_mode = getattr(policy, "mode", None)
        self.remaining_budget = max(0, int(remaining_budget))
        self.phase = state.phase
        self.target_paths = state.relevant_paths or state.target_paths
        status = getattr(validator_resolution_status, "value", validator_resolution_status)
        same_obligation = (next_required_check_id == self.next_required_check_id
                           and status == self.validator_resolution_status)
        self.next_required_check_id = str(next_required_check_id or "")
        self.validator_resolution_status = str(status or "")
        self.unresolved_reason = str(unresolved_reason or "")
        self.validation_paths = tuple(dict.fromkeys(validation_paths or self.target_paths))
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

    def restriction_reason(
        self,
        tool_name: str,
        arguments: dict | None,
        policy,
    ) -> str | None:
        """Block only another wasteful action; edits/validation stay open."""

        self.current_mode = getattr(policy, "mode", None)
        capabilities = self._capabilities(tool_name)
        is_read = "file.read" in capabilities

        if self.phase in {AgentPhase.VALIDATING, AgentPhase.FINALIZING} and self._inspection(tool_name):
            if self.validator_resolution_status == "target_unresolved":
                if self.validation_inspections >= self.UNRESOLVED_INSPECTION_LIMIT:
                    self._activate()
                    return (
                        f"Validation check {self.next_required_check_id or 'current'} remains unresolved after "
                        "one targeted inspection. Rebind it, resolve a capability, or report the concrete blocker."
                    )
                path = str((arguments or {}).get("path", "") or "").strip()
                if path and self.validation_paths and path not in self.validation_paths:
                    return (
                        f"Only proof-directed inspection for {self.next_required_check_id or 'the current check'} is "
                        f"allowed ({', '.join(self.validation_paths)}), not {path}."
                    )
                # The restriction boundary is invoked exactly once per tool
                # call. Count the granted inspection here so a model cannot
                # turn unresolved binding into open-ended reconnaissance.
                self.validation_inspections += 1
                return None
            if self.validator_resolution_status in {"capability_missing", "unsupported"}:
                return (
                    f"Validation check {self.next_required_check_id or 'current'} is {self.validator_resolution_status}; "
                    "source inspection cannot resolve this environment/blocker state."
                )
            return (
                "The current revision has an executable validation target. Run the relevant "
                "validator instead of unrelated reconnaissance."
            )
        if self.phase == AgentPhase.FIXING:
            if self._inspection(tool_name) and not is_read:
                return (
                    "Validation failed. Inspect at most one targeted source region, "
                    "then make the fix. Broad reconnaissance is unavailable."
                )
            if is_read and self.consecutive_inspections >= 1:
                return (
                    "The targeted failure context has already been inspected. "
                    "Make a concrete fix or report a blocker."
                )
            if is_read and self.target_paths:
                path = str((arguments or {}).get("path", "") or "").strip()
                if path not in self.target_paths:
                    return (
                        "FIXING permits one targeted read of a relevant failure path "
                        f"({', '.join(self.target_paths)}), not {path or 'an unspecified path'}."
                    )

        if tool_name == "replan" and not getattr(policy, "enable_replan", False):
            return "FAST mode is planless; replan is unavailable."

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
                "Full repository regression is not applicable to this isolated "
                "FAST task. Run one targeted acceptance validation instead."
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
