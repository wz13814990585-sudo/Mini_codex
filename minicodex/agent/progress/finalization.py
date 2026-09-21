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
        "因任务预算偏低，已进入收尾模式。"
        "不要把剩余步骤花在侦察上。仅运行缺失的验证、"
        "做必要的具体编辑、完成有证据的计划步骤，或报告阻塞原因。"
    )

    def __init__(self):
        self.active = False
        self.reconciled = False
        self.allow_proof_inspection = False

    def reset(self) -> None:
        self.active = False
        self.reconciled = False
        self.allow_proof_inspection = False

    def enter_if_needed(self, remaining_steps: int, policy) -> bool:
        if remaining_steps <= getattr(policy, "finalization_threshold", 2):
            newly_active = not self.active
            self.active = True
            return newly_active
        return False

    def restriction_reason(self, tool_name: str) -> str | None:
        if self.active and tool_name in self.BLOCKED_TOOLS and not self.allow_proof_inspection:
            return self.INSTRUCTION
        return None
