"""Side-effect-free control decisions returned by policy helpers."""

from dataclasses import dataclass

from ..reason_codes import ReasonCode


@dataclass(frozen=True)
class ControlDecision:
    restart: bool = False
    early_stop: str | None = None
    followup_message: str | None = None
    skipped_reason: str | None = None
    reason_code: ReasonCode | None = None
