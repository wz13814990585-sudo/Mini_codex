from dataclasses import dataclass
from enum import Enum


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

    READY = "ready"


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

    Required evidence:

    1. A meaningful edit exists.
    2. Acceptance evidence exists for the current revision.
    3. Full regression validation passed for the current
       revision.

    Full regression tests alone are intentionally
    insufficient.
    """

    def evaluate(
        self,
        *,
        edit_revision: int,
        has_edit: bool,
        acceptance_passed: bool,
        full_validation_passed: bool,
    ) -> CompletionDecision:

        # =====================================================
        # No Edit
        # =====================================================

        if not has_edit:

            return CompletionDecision(
                status=(
                    CompletionStatus
                    .NOT_READY
                ),
                edit_revision=(
                    edit_revision
                ),
                has_edit=False,
                acceptance_passed=False,
                full_validation_passed=(
                    full_validation_passed
                ),
                reason=(
                    "No successful edit has been "
                    "recorded for this task."
                ),
            )

        # =====================================================
        # Missing Acceptance Evidence
        # =====================================================

        if not acceptance_passed:

            return CompletionDecision(
                status=(
                    CompletionStatus
                    .NEEDS_ACCEPTANCE
                ),
                edit_revision=(
                    edit_revision
                ),
                has_edit=True,
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
                has_edit=True,
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
            has_edit=True,
            acceptance_passed=True,
            full_validation_passed=True,
            reason=(
                "The current edit revision has both "
                "acceptance evidence and successful "
                "full regression validation."
            ),
        )