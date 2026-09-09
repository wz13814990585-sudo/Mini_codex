"""Low-budget finalization restrictions for the shared loop."""


class FinalizationController:
    BLOCKED_TOOLS = {
        "read_file",
        "search_code",
        "search_symbol",
        "list_files",
        "git_status",
        "git_diff",
    }
    INSTRUCTION = (
        "Finalization mode is active because the task budget is low. "
        "Do not spend remaining steps on reconnaissance. Run only missing "
        "validation, make a necessary concrete edit, complete an evidenced "
        "plan step, or report a blocker."
    )

    def __init__(self):
        self.active = False
        self.reconciled = False

    def reset(self) -> None:
        self.active = False
        self.reconciled = False

    def enter_if_needed(self, remaining_steps: int, policy) -> bool:
        if remaining_steps <= getattr(policy, "finalization_threshold", 2):
            newly_active = not self.active
            self.active = True
            return newly_active
        return False

    def restriction_reason(self, tool_name: str) -> str | None:
        if self.active and tool_name in self.BLOCKED_TOOLS:
            return self.INSTRUCTION
        return None
