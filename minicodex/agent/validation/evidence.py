from dataclasses import dataclass, field
from enum import Enum

class ValidationOutcome(
    str,
    Enum,
):

    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


# =============================================================
# Validation Scope
# =============================================================


class ValidationScope(
    str,
    Enum,
):

    TARGETED = "targeted"
    FULL = "full"
    UNKNOWN = "unknown"


# =============================================================
# Validation Purpose
# =============================================================


class ValidationPurpose(
    str,
    Enum,
):

    ACCEPTANCE = "acceptance"
    REGRESSION = "regression"


class FailureDelta(str, Enum):
    PRE_EXISTING_FAILURE = "pre_existing_failure"
    NEW_FAILURE = "new_failure"
    RESOLVED_FAILURE = "resolved_failure"
    PERSISTING_FAILURE = "persisting_failure"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FailureComparison:
    new: tuple[str, ...] = ()
    resolved: tuple[str, ...] = ()
    persisting: tuple[str, ...] = ()

    @property
    def primary(self) -> FailureDelta:
        if self.new:
            return FailureDelta.NEW_FAILURE
        if self.resolved:
            return FailureDelta.RESOLVED_FAILURE
        if self.persisting:
            return FailureDelta.PERSISTING_FAILURE
        return FailureDelta.UNKNOWN


# =============================================================
# Validation Next Action
# =============================================================


class ValidationNextAction(
    str,
    Enum,
):

    NONE = "none"

    FIX_FAILURE = "fix_failure"

    RUN_ACCEPTANCE_VALIDATION = (
        "run_acceptance_validation"
    )

    RUN_FULL_VALIDATION = (
        "run_full_validation"
    )

    INVESTIGATE_INCONCLUSIVE = (
        "investigate_inconclusive"
    )

    TASK_VALIDATED = (
        "task_validated"
    )


# =============================================================
# Validation Evidence
# =============================================================


@dataclass(frozen=True)
class ValidationEvidence:

    tool_name: str

    execution_succeeded: bool

    outcome: ValidationOutcome

    scope: ValidationScope

    purpose: ValidationPurpose

    edit_revision: int

    check_id: str = ""
    requirement_ids: tuple[str, ...] = ()
    strength: int = 2
    agent_test_only: bool = False
    capability: str = ""

    passed: int = 0

    failed: int = 0

    errors: int = 0

    skipped: int = 0

    failed_count: int | None = None

    path: str | None = None

    summary: str = ""

    details: dict = field(
        default_factory=dict
    )

    failure_ids: tuple[str, ...] = ()

    unstable: bool = False

    environment_failure: bool = False

    @property
    def target(self) -> str:
        return str(self.details.get("target_identity") or self.path or "")

    @property
    def validation_key(self) -> str:
        normalized = " ".join(self.target.split())
        if self.tool_name != "run_command":
            normalized = normalized.replace("\\", "/")
            while normalized.startswith("./"):
                normalized = normalized[2:]
        return "|".join((self.tool_name, self.purpose.value, self.scope.value, normalized))

    @property
    def validation_passed(
        self,
    ) -> bool:

        return (
            self.outcome
            == ValidationOutcome.PASSED
        )

    @property
    def validation_failed(
        self,
    ) -> bool:

        return (
            self.outcome
            == ValidationOutcome.FAILED
        )

    @property
    def validation_inconclusive(
        self,
    ) -> bool:

        return (
            self.outcome
            == ValidationOutcome.INCONCLUSIVE
        )

    @property
    def is_full_suite(
        self,
    ) -> bool:

        return (
            self.scope
            == ValidationScope.FULL
        )

    @property
    def is_acceptance(
        self,
    ) -> bool:

        return (
            self.purpose
            == ValidationPurpose.ACCEPTANCE
        )

    @property
    def is_regression(
        self,
    ) -> bool:

        return (
            self.purpose
            == ValidationPurpose.REGRESSION
        )


# =============================================================
# Validation State
# =============================================================
