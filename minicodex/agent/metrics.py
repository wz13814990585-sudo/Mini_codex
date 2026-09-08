from dataclasses import dataclass, field

from ..llm.types import TokenUsage


@dataclass
class ExecutionMetrics:
    """Behavior metrics for one task; these never influence execution."""

    execution_mode: str | None = None
    intent: str | None = None
    llm_call_count: int = 0
    tool_call_count: int = 0
    inspection_tool_count: int = 0
    edit_tool_count: int = 0
    validation_tool_count: int = 0
    calls_before_first_edit: int | None = None
    calls_before_first_validation: int | None = None
    replan_count: int = 0
    action_required_trigger_count: int = 0
    rollback_count: int = 0
    max_steps_exhausted: bool = False
    total_prompt_tokens: int = 0
    final_outcome: str | None = None
    final_completion_reason: str | None = None
    final_reason_code: str | None = None
    false_completion: bool = False
    wrong_edit: bool = False

    def reset(self, execution_mode: str | None = None, *, intent: str | None = None) -> None:
        self.execution_mode = execution_mode
        self.intent = intent
        self.llm_call_count = 0
        self.tool_call_count = 0
        self.inspection_tool_count = 0
        self.edit_tool_count = 0
        self.validation_tool_count = 0
        self.calls_before_first_edit = None
        self.calls_before_first_validation = None
        self.replan_count = 0
        self.action_required_trigger_count = 0
        self.rollback_count = 0
        self.max_steps_exhausted = False
        self.total_prompt_tokens = 0
        self.final_outcome = None
        self.final_completion_reason = None
        self.final_reason_code = None
        self.false_completion = False
        self.wrong_edit = False

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
        self.llm_call_count = max(self.llm_call_count, int(llm_call_count))
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
            if self.calls_before_first_validation is None:
                self.calls_before_first_validation = llm_call_count
        if tool_name == "replan":
            self.replan_count += 1

    def finish(self, outcome: str, reason: str, reason_code=None) -> None:
        self.final_outcome = outcome
        self.final_completion_reason = reason
        self.final_reason_code = getattr(reason_code, "value", reason_code)

    def observe_llm(self, *, call_count: int, total_prompt_tokens: int) -> None:
        self.llm_call_count = max(0, int(call_count))
        self.total_prompt_tokens = max(0, int(total_prompt_tokens))

    def record_rollback(self) -> None:
        self.rollback_count += 1


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
