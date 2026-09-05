from dataclasses import dataclass, field

from ..llm.types import TokenUsage


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