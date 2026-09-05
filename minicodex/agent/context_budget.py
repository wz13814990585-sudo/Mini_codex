from dataclasses import dataclass
from enum import Enum


class ContextPressure(
    str,
    Enum,
):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class ContextBudget:
    """
    Track recent prompt-size pressure.

    This is not cumulative token usage.

    It represents the most recently observed
    prompt size and classifies how close the
    Agent is to its configured context budget.
    """

    max_context_tokens: int = 64000

    warning_ratio: float = 0.60
    critical_ratio: float = 0.80

    last_prompt_tokens: int = 0

    # =========================================================
    # Reset
    # =========================================================

    def reset(
        self,
    ) -> None:

        self.last_prompt_tokens = 0

    # =========================================================
    # Observe
    # =========================================================

    def observe(
        self,
        prompt_tokens: int,
    ) -> None:

        self.last_prompt_tokens = max(
            0,
            int(
                prompt_tokens
            ),
        )

    # =========================================================
    # Usage Ratio
    # =========================================================

    @property
    def usage_ratio(
        self,
    ) -> float:

        if (
            self.max_context_tokens
            <= 0
        ):
            return 0.0

        return (
            self.last_prompt_tokens
            / self.max_context_tokens
        )

    # =========================================================
    # Pressure
    # =========================================================

    @property
    def pressure(
        self,
    ) -> ContextPressure:

        if (
            self.usage_ratio
            >= self.critical_ratio
        ):

            return (
                ContextPressure.CRITICAL
            )

        if (
            self.usage_ratio
            >= self.warning_ratio
        ):

            return (
                ContextPressure.WARNING
            )

        return (
            ContextPressure.NORMAL
        )