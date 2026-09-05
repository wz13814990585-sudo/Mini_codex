from dataclasses import dataclass
from enum import Enum

from ..tools.results import ToolResult


# =============================================================
# Validation Outcome
# =============================================================


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
# Validation Next Action
# =============================================================


class ValidationNextAction(
    str,
    Enum,
):

    """
    Deterministic recommendation produced by the
    validation pipeline.

    The LLM still decides HOW to act, but Harness decides
    what level of validation evidence is still required.
    """

    NONE = "none"

    FIX_FAILURE = "fix_failure"

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
    """
    Normalized behavioral validation evidence.

    Important concepts are intentionally separated:

    execution_succeeded:
        Did the validation tool itself execute correctly?

    outcome:
        What did the validation say about the code?

    scope:
        How broad was the validation?

    edit_revision:
        Which code revision did this evidence validate?
    """

    tool_name: str

    execution_succeeded: bool

    outcome: ValidationOutcome

    scope: ValidationScope

    edit_revision: int

    passed: int = 0

    failed: int = 0

    errors: int = 0

    skipped: int = 0

    failed_count: int | None = None

    path: str | None = None

    summary: str = ""

    # =========================================================
    # Convenience
    # =========================================================

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


# =============================================================
# Validation State
# =============================================================


@dataclass
class ValidationState:
    """
    Validation state for the current workspace edit revision.

    Every successful edit invalidates validation evidence
    from older revisions.
    """

    edit_revision: int = 0

    has_edit: bool = False

    targeted_passed: bool = False

    full_passed: bool = False

    latest_evidence: (
        ValidationEvidence
        | None
    ) = None

    # =========================================================
    # Reset
    # =========================================================

    def reset(
        self,
    ) -> None:

        self.edit_revision = 0

        self.has_edit = False

        self.targeted_passed = False

        self.full_passed = False

        self.latest_evidence = None


# =============================================================
# Validation Pipeline
# =============================================================


class ValidationPipeline:
    """
    Normalize validation results and manage validation
    escalation for the current edit revision.

    Core policy:

    Edit
        ↓
    validation evidence becomes stale

    Targeted PASS
        ↓
    still requires full validation

    Full PASS
        ↓
    current edit revision becomes fully validated
    """

    def __init__(
        self,
    ):

        self.state = (
            ValidationState()
        )

    # =========================================================
    # Reset
    # =========================================================

    def reset(
        self,
    ) -> None:

        self.state.reset()

    # =========================================================
    # Record Edit
    # =========================================================

    def record_edit(
        self,
    ) -> int:
        """
        Record one successful meaningful edit.

        Every edit creates a new revision and invalidates
        all validation evidence for the previous code state.
        """

        self.state.edit_revision += 1

        self.state.has_edit = True

        self.state.targeted_passed = False

        self.state.full_passed = False

        self.state.latest_evidence = None

        return (
            self.state.edit_revision
        )

    # =========================================================
    # Observe Tool Result
    # =========================================================

    def observe(
        self,
        tool_name: str,
        arguments: dict,
        result: ToolResult,
    ) -> ValidationEvidence | None:

        if (
            tool_name
            != "run_tests"
        ):

            return None

        evidence = (
            self._from_run_tests(
                arguments=arguments,
                result=result,
            )
        )

        self._record_evidence(
            evidence
        )

        return evidence

    # =========================================================
    # Record Evidence
    # =========================================================

    def _record_evidence(
        self,
        evidence: ValidationEvidence,
    ) -> None:

        self.state.latest_evidence = (
            evidence
        )

        # =====================================================
        # Only PASS evidence can move validation forward.
        # =====================================================

        if (
            evidence.outcome
            != ValidationOutcome.PASSED
        ):

            return

        # =====================================================
        # Targeted PASS
        # =====================================================

        if (
            evidence.scope
            == ValidationScope.TARGETED
        ):

            self.state.targeted_passed = (
                True
            )

            return

        # =====================================================
        # Full PASS
        # =====================================================

        if (
            evidence.scope
            == ValidationScope.FULL
        ):

            self.state.full_passed = (
                True
            )

    # =========================================================
    # Next Action
    # =========================================================

    def next_action(
        self,
        evidence: (
            ValidationEvidence
            | None
        ) = None,
    ) -> ValidationNextAction:
        """
        Return the deterministic validation action implied
        by current evidence.

        This does not tell the LLM HOW to fix code.
        It only tells orchestration what validation state
        currently permits.
        """

        current = (
            evidence
            or self.state.latest_evidence
        )

        if current is None:

            return (
                ValidationNextAction.NONE
            )

        # =====================================================
        # Validation Tool Could Not Produce Reliable Evidence
        # =====================================================

        if (
            current.outcome
            == ValidationOutcome.INCONCLUSIVE
        ):

            return (
                ValidationNextAction
                .INVESTIGATE_INCONCLUSIVE
            )

        # =====================================================
        # Validation Failed
        # =====================================================

        if (
            current.outcome
            == ValidationOutcome.FAILED
        ):

            return (
                ValidationNextAction
                .FIX_FAILURE
            )

        # =====================================================
        # Targeted Validation Passed
        #
        # Useful evidence, but insufficient for final task
        # completion after an edit.
        # =====================================================

        if (
            current.scope
            == ValidationScope.TARGETED
        ):

            if (
                self.state.has_edit
            ):

                return (
                    ValidationNextAction
                    .RUN_FULL_VALIDATION
                )

            return (
                ValidationNextAction.NONE
            )

        # =====================================================
        # Full Validation Passed
        # =====================================================

        if (
            current.scope
            == ValidationScope.FULL
        ):

            if (
                self.state.has_edit
                and self.state.full_passed
            ):

                return (
                    ValidationNextAction
                    .TASK_VALIDATED
                )

            return (
                ValidationNextAction.NONE
            )

        return (
            ValidationNextAction.NONE
        )

    # =========================================================
    # Current Revision Fully Validated
    # =========================================================

    def current_edit_validated(
        self,
    ) -> bool:
        """
        True only when the current code revision has:

        - at least one recorded edit
        - a successful full validation after that edit
        """

        return bool(
            self.state.has_edit
            and self.state.full_passed
        )

    # =========================================================
    # Requires Full Validation
    # =========================================================

    def requires_full_validation(
        self,
    ) -> bool:
        """
        True when useful targeted evidence exists but the
        current edit revision still lacks a successful
        full validation.
        """

        return bool(
            self.state.has_edit
            and self.state.targeted_passed
            and not self.state.full_passed
        )

    # =========================================================
    # Pytest Result Normalization
    # =========================================================

    def _from_run_tests(
        self,
        *,
        arguments: dict,
        result: ToolResult,
    ) -> ValidationEvidence:

        path = str(
            arguments.get(
                "path",
                ".",
            )
        ).strip()

        scope = (
            self._test_scope(
                path
            )
        )

        # =====================================================
        # Tool Execution Failure
        # =====================================================

        if not result.success:

            return ValidationEvidence(
                tool_name="run_tests",
                execution_succeeded=False,
                outcome=(
                    ValidationOutcome
                    .INCONCLUSIVE
                ),
                scope=scope,
                edit_revision=(
                    self.state
                    .edit_revision
                ),
                failed_count=None,
                path=path,
                summary=(
                    result.summary
                ),
            )

        # =====================================================
        # Structured Pytest Data
        # =====================================================

        tests_passed = (
            result.data.get(
                "tests_passed"
            )
        )

        passed = (
            self._safe_int(
                result.data.get(
                    "passed",
                    0,
                )
            )
        )

        failed = (
            self._safe_int(
                result.data.get(
                    "failed",
                    0,
                )
            )
        )

        errors = (
            self._safe_int(
                result.data.get(
                    "errors",
                    0,
                )
            )
        )

        skipped = (
            self._safe_int(
                result.data.get(
                    "skipped",
                    0,
                )
            )
        )

        # =====================================================
        # Validation Passed
        # =====================================================

        if (
            tests_passed
            is True
        ):

            return ValidationEvidence(
                tool_name="run_tests",
                execution_succeeded=True,
                outcome=(
                    ValidationOutcome
                    .PASSED
                ),
                scope=scope,
                edit_revision=(
                    self.state
                    .edit_revision
                ),
                passed=passed,
                failed=failed,
                errors=errors,
                skipped=skipped,
                failed_count=0,
                path=path,
                summary=(
                    result.summary
                ),
            )

        # =====================================================
        # Validation Failed
        # =====================================================

        failure_total = (
            failed
            + errors
        )

        if (
            failure_total
            > 0
        ):

            return ValidationEvidence(
                tool_name="run_tests",
                execution_succeeded=True,
                outcome=(
                    ValidationOutcome
                    .FAILED
                ),
                scope=scope,
                edit_revision=(
                    self.state
                    .edit_revision
                ),
                passed=passed,
                failed=failed,
                errors=errors,
                skipped=skipped,
                failed_count=(
                    failure_total
                ),
                path=path,
                summary=(
                    result.summary
                ),
            )

        # =====================================================
        # Inconclusive
        # =====================================================

        return ValidationEvidence(
            tool_name="run_tests",
            execution_succeeded=True,
            outcome=(
                ValidationOutcome
                .INCONCLUSIVE
            ),
            scope=scope,
            edit_revision=(
                self.state
                .edit_revision
            ),
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            failed_count=None,
            path=path,
            summary=(
                result.summary
            ),
        )

    # =========================================================
    # Scope Detection
    # =========================================================

    @staticmethod
    def _test_scope(
        path: str,
    ) -> ValidationScope:

        normalized = (
            path.strip()
        )

        if normalized in {
            "",
            ".",
            "./",
        }:

            return (
                ValidationScope.FULL
            )

        if normalized:

            return (
                ValidationScope
                .TARGETED
            )

        return (
            ValidationScope.UNKNOWN
        )

    # =========================================================
    # Safe Integer
    # =========================================================

    @staticmethod
    def _safe_int(
        value,
    ) -> int:

        try:

            return int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):

            return 0