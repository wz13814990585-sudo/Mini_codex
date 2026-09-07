from dataclasses import dataclass
from enum import Enum

from .regression_policy import RegressionRequirement


class CompletionStatus(
    str,
    Enum,
):

    NOT_READY = "not_ready"

    NEEDS_ACCEPTANCE = (
        "needs_acceptance"
    )

    NEEDS_FULL_VALIDATION = (
        "needs_full_validation"
    )

    NEEDS_RELEVANT_VALIDATION = "needs_relevant_validation"

    READY = "ready"


class TaskOutcome(str, Enum):
    ALREADY_SATISFIED = "already_satisfied"
    EDITED_AND_VALIDATED = "edited_and_validated"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class CompletionDecision:
    """
    Deterministic task-completion decision.

    The CompletionGate does not decide whether code
    is semantically good by itself.

    It only checks whether the required independent
    pieces of evidence exist for the CURRENT edit
    revision.
    """

    status: CompletionStatus

    edit_revision: int

    has_edit: bool

    acceptance_passed: bool

    full_validation_passed: bool

    reason: str

    outcome: TaskOutcome = TaskOutcome.INCOMPLETE

    @property
    def can_complete(
        self,
    ) -> bool:

        return (
            self.status
            == CompletionStatus.READY
        )


class CompletionGate:
    """
    Final deterministic gate before an editing task may
    be considered complete.

    Baseline evidence:

    1. Acceptance proves the requested state for the current revision.
    2. Regression evidence is proportional to the active policy.
    3. An edit distinguishes edited completion from already-satisfied
       completion; it is not itself mandatory.

    Full regression tests alone are intentionally insufficient because
    acceptance remains an independent requirement by default.
    """

    def evaluate(
        self,
        *,
        edit_revision: int,
        has_edit: bool,
        acceptance_passed: bool,
        full_validation_passed: bool,
        relevant_validation_passed: bool = False,
        require_acceptance: bool = True,
        regression_requirement: RegressionRequirement = (
            RegressionRequirement.REQUIRED
        ),
        allow_already_satisfied: bool = True,
    ) -> CompletionDecision:

        # =====================================================
        # No Edit
        # =====================================================

        if not has_edit and not (
            allow_already_satisfied
            and (acceptance_passed or not require_acceptance)
        ):

            return CompletionDecision(
                status=(
                    CompletionStatus
                    .NOT_READY
                ),
                edit_revision=(
                    edit_revision
                ),
                has_edit=False,
                acceptance_passed=acceptance_passed,
                full_validation_passed=(
                    full_validation_passed
                ),
                reason=(
                    "No successful edit has been "
                    "recorded and acceptance has not proven that the "
                    "requested state already exists."
                ),
            )

        # =====================================================
        # Missing Acceptance Evidence
        # =====================================================

        if require_acceptance and not acceptance_passed:

            return CompletionDecision(
                status=(
                    CompletionStatus
                    .NEEDS_ACCEPTANCE
                ),
                edit_revision=(
                    edit_revision
                ),
                has_edit=has_edit,
                acceptance_passed=False,
                full_validation_passed=(
                    full_validation_passed
                ),
                reason=(
                    "The current edit revision does not "
                    "have acceptance evidence showing "
                    "that the requested behavior works."
                ),
            )

        if regression_requirement == RegressionRequirement.NOT_APPLICABLE:
            return CompletionDecision(
                status=CompletionStatus.READY,
                edit_revision=edit_revision,
                has_edit=has_edit,
                acceptance_passed=acceptance_passed,
                full_validation_passed=full_validation_passed,
                reason=(
                    "Acceptance passed and full repository regression is "
                    "not applicable to this change scope."
                ),
                outcome=(
                    TaskOutcome.EDITED_AND_VALIDATED
                    if has_edit
                    else TaskOutcome.ALREADY_SATISFIED
                ),
            )

        if regression_requirement in {
            RegressionRequirement.RELEVANT_ONLY,
            RegressionRequirement.UNKNOWN,
        }:
            if not (relevant_validation_passed or full_validation_passed):
                return CompletionDecision(
                    status=CompletionStatus.NEEDS_RELEVANT_VALIDATION,
                    edit_revision=edit_revision,
                    has_edit=has_edit,
                    acceptance_passed=acceptance_passed,
                    full_validation_passed=full_validation_passed,
                    reason=(
                        "Acceptance passed, but relevant regression "
                        "evidence is still required for this change scope."
                    ),
                )
            return CompletionDecision(
                status=CompletionStatus.READY,
                edit_revision=edit_revision,
                has_edit=has_edit,
                acceptance_passed=acceptance_passed,
                full_validation_passed=full_validation_passed,
                reason=(
                    "The current edit revision has acceptance and relevant "
                    "regression evidence."
                ),
                outcome=(
                    TaskOutcome.EDITED_AND_VALIDATED
                    if has_edit
                    else TaskOutcome.ALREADY_SATISFIED
                ),
            )

        # =====================================================
        # Acceptance Passed But Regression Not Complete
        # =====================================================

        if not full_validation_passed:

            return CompletionDecision(
                status=(
                    CompletionStatus
                    .NEEDS_FULL_VALIDATION
                ),
                edit_revision=(
                    edit_revision
                ),
                has_edit=has_edit,
                acceptance_passed=True,
                full_validation_passed=False,
                reason=(
                    "Acceptance validation passed, but "
                    "the current edit revision still "
                    "requires full regression validation."
                ),
            )

        # =====================================================
        # Complete
        # =====================================================

        return CompletionDecision(
            status=(
                CompletionStatus.READY
            ),
            edit_revision=(
                edit_revision
            ),
            has_edit=has_edit,
            acceptance_passed=True,
            full_validation_passed=True,
            reason=(
                "The current edit revision has both "
                "acceptance evidence and successful "
                "full regression validation."
            ),
            outcome=(
                TaskOutcome.EDITED_AND_VALIDATED
                if has_edit
                else TaskOutcome.ALREADY_SATISFIED
            ),
        )
