"""Central task orchestration state shared by the Agent Harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .completion import TaskOutcome
from .execution_mode import ExecutionMode
from .validation import ValidationOutcome


class AgentPhase(str, Enum):
    """Coarse execution phase used by deterministic control policies."""

    INSPECTING = "inspecting"
    ACTING = "acting"
    VALIDATING = "validating"
    FIXING = "fixing"
    FINALIZING = "finalizing"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass
class TaskState:
    """One compact read-model for all facts that influence orchestration.

    Tool output and filesystem contents remain the source of truth.  This
    object only projects their latest deterministic state so controllers do
    not each maintain competing copies of the same facts.
    """

    mode: ExecutionMode | None = None
    phase: AgentPhase = AgentPhase.INSPECTING
    user_request: str = ""
    target_paths: tuple[str, ...] = field(default_factory=tuple)
    edit_revision: int = 0
    validation_revision: int = 0
    rollback_revision: int = 0
    plan_revision: int = 0
    completed_plan_steps: tuple[int, ...] = field(default_factory=tuple)
    has_edit: bool = False
    acceptance_passed: bool = False
    relevant_validation_passed: bool = False
    full_validation_passed: bool = False
    consecutive_inspections: int = 0
    consecutive_no_state_change: int = 0
    remaining_steps: int = 0
    outcome: TaskOutcome = TaskOutcome.INCOMPLETE
    latest_validation_outcome: ValidationOutcome | None = None

    # V3 compatibility names.  They are computed views, not duplicate state.
    @property
    def validation_version(self) -> int:
        return self.validation_revision

    @property
    def plan_version(self) -> int:
        return self.plan_revision

    def progress_key(self) -> tuple:
        """Return only monotonic facts that count as real task progress."""

        return (
            self.edit_revision,
            self.validation_revision,
            self.rollback_revision,
            self.plan_revision,
            self.completed_plan_steps,
        )

    def transition_for_tool(
        self,
        tool_name: str,
        *,
        success: bool,
        validation_outcome: ValidationOutcome | None = None,
        stale_edit: bool = False,
    ) -> AgentPhase:
        """Apply the small deterministic phase state machine."""

        if self.phase in {AgentPhase.DONE, AgentPhase.BLOCKED}:
            return self.phase
        if stale_edit:
            self.phase = AgentPhase.FIXING
        elif tool_name in {"patch_file", "replace_lines", "replace_symbol", "write_file"}:
            self.phase = AgentPhase.VALIDATING if success else AgentPhase.ACTING
        elif tool_name in {"run_tests", "validate_static_web"} or (
            tool_name == "run_command" and validation_outcome is not None
        ):
            if validation_outcome == ValidationOutcome.FAILED:
                self.phase = AgentPhase.FIXING
            elif validation_outcome == ValidationOutcome.PASSED:
                self.phase = AgentPhase.FINALIZING
            else:
                self.phase = AgentPhase.VALIDATING
        elif tool_name in {
            "read_file", "search_code", "search_symbol", "list_files",
            "git_status", "git_diff",
        }:
            # Observations do not advance the phase by themselves.  The
            # ActionController moves INSPECTING -> ACTING only when the
            # bounded reconnaissance allowance is actually exhausted.
            pass
        elif tool_name in {"complete_plan_step", "replan", "automatic_rollback"}:
            self.phase = AgentPhase.ACTING
        return self.phase

    def mark_finalizing(self) -> None:
        if self.phase not in {AgentPhase.DONE, AgentPhase.BLOCKED}:
            self.phase = AgentPhase.FINALIZING

    def require_action(self) -> None:
        if self.phase not in {
            AgentPhase.VALIDATING,
            AgentPhase.FIXING,
            AgentPhase.FINALIZING,
            AgentPhase.DONE,
            AgentPhase.BLOCKED,
        }:
            self.phase = AgentPhase.ACTING

    def finish(self, outcome: TaskOutcome) -> None:
        self.outcome = outcome
        if outcome == TaskOutcome.BLOCKED:
            self.phase = AgentPhase.BLOCKED
        elif outcome in {
            TaskOutcome.ALREADY_SATISFIED,
            TaskOutcome.EDITED_AND_VALIDATED,
        }:
            self.phase = AgentPhase.DONE
