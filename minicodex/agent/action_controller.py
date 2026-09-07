"""One deterministic source of truth for action/progress pressure."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskProgressState:
    """Monotonic task facts; observations are deliberately excluded."""

    edit_revision: int
    validation_version: int
    completed_plan_steps: int
    plan_version: int
    rollback_revision: int


class ActionController:
    """Bound reconnaissance without confusing observations with progress.

    The controller never mutates provider messages and never executes tools.
    It only observes deterministic task state and decides when ordinary
    reconnaissance must yield to edit, validation, plan progress, or a
    concrete blocker.
    """

    INSPECTION_TOOLS = frozenset(
        {
            "read_file",
            "search_code",
            "search_symbol",
            "list_files",
            "git_status",
            "git_diff",
        }
    )
    EDIT_TOOLS = frozenset(
        {"write_file", "patch_file", "replace_lines", "replace_symbol"}
    )
    VALIDATION_TOOLS = frozenset(
        {"validate_static_web", "run_tests"}
    )
    INSTRUCTION = (
        "You have enough context. Make a concrete edit, run the required "
        "validation, or report a concrete blocker."
    )

    def __init__(self) -> None:
        self.reset()

    def reset(self, state: TaskProgressState | None = None) -> None:
        self.last_state = state
        self.consecutive_inspections = 0
        self.consecutive_no_state_change = 0
        self.action_required = False
        self.action_required_trigger_count = 0
        self.has_edit = bool(state and state.edit_revision > 0)
        self.acceptance_missing = True
        self.current_mode = None
        self.remaining_budget: int | None = None

    def update_context(
        self,
        *,
        state: TaskProgressState,
        policy,
        remaining_budget: int,
        acceptance_missing: bool,
    ) -> None:
        """Expose current deterministic task context without adding pressure."""

        if self.last_state is None:
            self.last_state = state
        self.has_edit = state.edit_revision > 0
        self.acceptance_missing = bool(acceptance_missing)
        self.current_mode = getattr(policy, "mode", None)
        self.remaining_budget = max(0, int(remaining_budget))

    def observe_action(self, tool_name: str, state: TaskProgressState) -> bool:
        """Record one completed tool action and return state-change truth."""

        changed = self.last_state is not None and state != self.last_state
        self.last_state = state
        self.has_edit = state.edit_revision > 0

        if changed:
            self.consecutive_inspections = 0
            self.consecutive_no_state_change = 0
            self.action_required = False
            return True

        self.consecutive_no_state_change += 1
        if tool_name in self.INSPECTION_TOOLS:
            self.consecutive_inspections += 1
        else:
            self.consecutive_inspections = 0
        return False

    def update_pressure(self, policy) -> bool:
        inspection_limit = getattr(policy, "max_inspection_calls", None)
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

        if tool_name == "complete_plan_step" and not getattr(
            policy, "use_plan", False
        ):
            return "FAST mode has no active plan; complete_plan_step is unavailable."
        if tool_name == "replan" and not getattr(policy, "enable_replan", False):
            return "FAST mode is planless; replan is unavailable."

        if (
            tool_name == "run_tests"
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

        inspection_limit = getattr(policy, "max_inspection_calls", None)
        next_inspection_exceeds_budget = bool(
            inspection_limit is not None
            and tool_name in self.INSPECTION_TOOLS
            and self.consecutive_inspections >= inspection_limit
        )
        if next_inspection_exceeds_budget:
            self._activate()

        if not self.action_required:
            return None

        if tool_name in self.EDIT_TOOLS | self.VALIDATION_TOOLS:
            return None
        if tool_name == "run_command" and str(
            (arguments or {}).get("purpose", "diagnostic")
        ).strip().lower() == "acceptance":
            return None
        if tool_name == "complete_plan_step" and getattr(policy, "use_plan", False):
            return None
        if tool_name == "replan" and getattr(policy, "enable_replan", False):
            return None
        if tool_name in self.INSPECTION_TOOLS or tool_name == "run_command":
            return self.INSTRUCTION
        return None

    def _activate(self) -> None:
        if not self.action_required:
            self.action_required = True
            self.action_required_trigger_count += 1
