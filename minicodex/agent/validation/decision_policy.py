from .evidence import ValidationEvidence, ValidationNextAction, ValidationOutcome


class ValidationDecisionPolicy:
    def __init__(self, ledger):
        self.state = ledger

    def next_action(
        self,
        evidence: (
            ValidationEvidence
            | None
        ) = None,
    ) -> ValidationNextAction:

        current = (
            evidence
            or self.state.latest_evidence
        )

        if current is not None and current.unstable:
            return ValidationNextAction.INVESTIGATE_INCONCLUSIVE

        if (
            current
            is None
        ):

            return (
                ValidationNextAction.NONE
            )

        if (
            current.outcome
            == ValidationOutcome.INCONCLUSIVE
        ):

            return (
                ValidationNextAction
                .INVESTIGATE_INCONCLUSIVE
            )

        if (
            current.outcome
            == ValidationOutcome.FAILED
        ):

            return (
                ValidationNextAction
                .FIX_FAILURE
            )

        if self.next_required_check() is not None:
            return ValidationNextAction.RUN_CHECK

        if not (
            self.state.has_edit
        ):

            return (
                ValidationNextAction.NONE
            )

        if (
            self.state.acceptance_passed
            and self.state.full_passed
        ):

            return (
                ValidationNextAction
                .TASK_VALIDATED
            )

        if (
            self.state.acceptance_passed
            and not self.state.full_passed
        ):

            return (
                ValidationNextAction
                .RUN_FULL_VALIDATION
            )

        if not (
            self.state.acceptance_passed
        ):

            return (
                ValidationNextAction
                .RUN_ACCEPTANCE_VALIDATION
            )

        return (
            ValidationNextAction.NONE
        )

    def next_required_check(self):
        """Canonical policy answer: the first current proof obligation still open."""
        return next((check for check in self.state.plan.checks
                     if check.required and self.state.proof(check.id) is None), None)

    # =========================================================
    # Current Full Regression Evidence
    # =========================================================

    def current_edit_validated(
        self,
    ) -> bool:

        return bool(
            self.state.has_edit
            and self.state.full_passed
        )

    # =========================================================
    # Acceptance Evidence
    # =========================================================

    def current_acceptance_passed(
        self,
    ) -> bool:

        return bool(
            self.state.has_edit
            and self.state.acceptance_passed
        )

    # =========================================================
    # Requires Full Regression
    # =========================================================

    def requires_full_validation(
        self,
    ) -> bool:

        return bool(
            self.state.has_edit
            and self.state.acceptance_passed
            and not self.state.full_passed
        )

    # =========================================================
    # Requires Acceptance
    # =========================================================

    def requires_acceptance_validation(
        self,
    ) -> bool:

        return bool(
            self.state.has_edit
            and not self.state.acceptance_passed
        )
