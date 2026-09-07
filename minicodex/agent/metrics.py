from dataclasses import dataclass, field

from ..llm.types import TokenUsage


@dataclass
class ExecutionMetrics:
    """Behavior metrics for one task; these never influence execution."""

    execution_mode: str | None = None
    tool_call_count: int = 0
    inspection_tool_count: int = 0
    edit_tool_count: int = 0
    validation_tool_count: int = 0
    calls_before_first_edit: int | None = None
    replan_count: int = 0
    action_required_trigger_count: int = 0
    final_outcome: str | None = None
    final_completion_reason: str | None = None

    def reset(self, execution_mode: str | None = None) -> None:
        self.execution_mode = execution_mode
        self.tool_call_count = 0
        self.inspection_tool_count = 0
        self.edit_tool_count = 0
        self.validation_tool_count = 0
        self.calls_before_first_edit = None
        self.replan_count = 0
        self.action_required_trigger_count = 0
        self.final_outcome = None
        self.final_completion_reason = None

    def record_tool(
        self,
        tool_name: str,
        *,
        llm_call_count: int,
        arguments: dict | None = None,
        success: bool = True,
    ) -> None:
        from .action_controller import ActionController

        self.tool_call_count += 1
        if tool_name in ActionController.INSPECTION_TOOLS:
            self.inspection_tool_count += 1
        if tool_name in ActionController.EDIT_TOOLS and success:
            self.edit_tool_count += 1
            if self.calls_before_first_edit is None:
                self.calls_before_first_edit = llm_call_count
        if tool_name in ActionController.VALIDATION_TOOLS or (
            tool_name == "run_command"
            and str((arguments or {}).get("purpose", "diagnostic")).lower()
            == "acceptance"
        ):
            self.validation_tool_count += 1
        if tool_name == "replan":
            self.replan_count += 1

    def finish(self, outcome: str, reason: str) -> None:
        self.final_outcome = outcome
        self.final_completion_reason = reason


@dataclass
class TokenMetrics:
    """
    Track token usage for the current Agent task.

    The metrics object accumulates token usage from
    multiple LLM calls during one task.
    """

    total: TokenUsage = field(
        default_factory=TokenUsage
    )

    call_count: int = 0

    # =========================================================
    # Reset
    # =========================================================

    def reset(self) -> None:
        """
        Reset all token metrics for a new task.
        """

        self.total = TokenUsage()
        self.call_count = 0

    # =========================================================
    # Record
    # =========================================================

    def record(
        self,
        usage: TokenUsage,
    ) -> None:
        """
        Add one LLM call's token usage to the task total.
        """

        self.total.prompt_tokens += (
            usage.prompt_tokens
        )

        self.total.completion_tokens += (
            usage.completion_tokens
        )

        self.total.total_tokens += (
            usage.total_tokens
        )

        self.call_count += 1
