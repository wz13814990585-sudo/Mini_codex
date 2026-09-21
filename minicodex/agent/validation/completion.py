"""Public completion result types."""

from dataclasses import dataclass
from enum import Enum


class CompletionStatus(str, Enum):
    NOT_READY = "not_ready"
    NEEDS_ACCEPTANCE = "needs_acceptance"
    NEEDS_FULL_VALIDATION = "needs_full_validation"
    NEEDS_RELEVANT_VALIDATION = "needs_relevant_validation"
    READY = "ready"


class TaskOutcome(str, Enum):
    INFORMATIONAL_ANSWER = "informational_answer"
    INSPECTED = "inspected"
    ALREADY_SATISFIED = "already_satisfied"
    EDITED_AND_VALIDATED = "edited_and_validated"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class CompletionDecision:
    status: CompletionStatus
    edit_revision: int
    has_edit: bool
    acceptance_passed: bool
    full_validation_passed: bool
    reason: str
    outcome: TaskOutcome = TaskOutcome.INCOMPLETE

    @property
    def can_complete(self) -> bool:
        return self.status == CompletionStatus.READY
