"""Side-effect-free control decisions returned by policy helpers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ControlDecision:
    restart: bool = False
    early_stop: str | None = None
    followup_message: str | None = None
    skipped_reason: str | None = None

    def __iter__(self):
        """Keep legacy two-value unpacking while callers migrate."""
        yield self.early_stop
        yield self.restart

