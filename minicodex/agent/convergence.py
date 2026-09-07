"""Task-state fingerprints and convergence-mode restrictions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskProgressState:
    edit_revision: int
    completed_step_count: int
    validation_version: int
    plan_version: int
    rollback_revision: int


class ConvergenceController:
    INSPECTION_TOOLS = {
        "read_file",
        "search_code",
        "search_symbol",
        "list_files",
        "git_status",
        "git_diff",
    }
    INSTRUCTION = (
        "Convergence mode is active. Free-form reconnaissance is blocked. "
        "Make a concrete edit, run validation, complete an evidenced plan "
        "step, replan if policy allows it, or report an explicit blocker."
    )

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.inspection_calls = 0
        self.active = False
        self.last_state: TaskProgressState | None = None

    def observe_state(self, state: TaskProgressState) -> bool:
        changed = self.last_state is not None and state != self.last_state
        self.last_state = state
        if changed:
            self.inspection_calls = 0
            self.active = False
        return changed

    def record_tool(self, tool_name: str) -> None:
        if tool_name in self.INSPECTION_TOOLS:
            self.inspection_calls += 1

    def restriction_reason(self, tool_name: str, policy) -> str | None:
        limit = getattr(policy, "max_inspection_calls", None)
        over_budget = (
            limit is not None
            and tool_name in self.INSPECTION_TOOLS
            and self.inspection_calls >= limit
        )
        if (self.active or over_budget) and tool_name in self.INSPECTION_TOOLS:
            self.active = True
            return self.INSTRUCTION
        return None

