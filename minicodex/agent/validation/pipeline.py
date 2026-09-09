from dataclasses import dataclass, field, replace
from enum import Enum

from ...tools.results import ToolResult


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
    def validation_key(self) -> str:
        normalized = " ".join(str(self.path or "").split())
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


@dataclass
class ValidationState:

    edit_revision: int = 0

    has_edit: bool = False

    targeted_passed: bool = False

    acceptance_passed: bool = False

    full_passed: bool = False

    latest_evidence: (
        ValidationEvidence
        | None
    ) = None

    evidence_sequence: int = 0

    evidence_history: list[ValidationEvidence] = field(default_factory=list)

    baseline_by_key: dict[str, ValidationEvidence] = field(default_factory=dict)

    unstable_keys: set[str] = field(default_factory=set)

    def reset(
        self,
    ) -> None:

        self.edit_revision = 0

        self.has_edit = False

        self.targeted_passed = False

        self.acceptance_passed = False

        self.full_passed = False

        self.latest_evidence = None

        self.evidence_sequence = 0
        self.evidence_history.clear()
        self.baseline_by_key.clear()
        self.unstable_keys.clear()


# =============================================================
# Validation Pipeline
# =============================================================


class ValidationPipeline:

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

        self.state.edit_revision += 1

        self.state.has_edit = True

        # A new physical workspace revision invalidates
        # every piece of validation evidence.
        self.state.targeted_passed = False

        self.state.acceptance_passed = False

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

        if tool_name in {"validate_static_web", "validate_browser_app"}:

            evidence = self._from_static_web(
                arguments=arguments,
                result=result,
                tool_name=tool_name,
            )

        elif tool_name == "run_command":

            if (
                str(
                    arguments.get(
                        "purpose",
                        "diagnostic",
                    )
                ).strip().lower()
                != "acceptance"
            ):
                return None

            evidence = self._from_run_command(
                arguments=arguments,
                result=result,
            )

        elif tool_name == "run_tests":

            evidence = self._from_run_tests(
                arguments=arguments,
                result=result,
            )

        else:
            return None

        evidence = self._mark_stability(evidence)
        self._record_evidence(
            evidence
        )

        # Expose one normalized validation result shape to downstream traces,
        # summaries, and evaluation code regardless of the concrete tool.
        result.data.update(
            {
                "purpose": evidence.purpose.value,
                "outcome": evidence.outcome.value,
                "path": evidence.path,
                "failed_count": evidence.failed_count,
                "validation_summary": evidence.summary,
                "validation_key": evidence.validation_key,
                "failure_ids": list(evidence.failure_ids),
                "unstable": evidence.unstable,
            }
        )

        return evidence

    def _from_static_web(
        self,
        *,
        arguments: dict,
        result: ToolResult,
        tool_name: str = "validate_static_web",
    ) -> ValidationEvidence:
        outcome_value = str(
            result.data.get(
                "outcome",
                "inconclusive",
            )
        ).strip().lower()
        outcome = {
            "passed": ValidationOutcome.PASSED,
            "failed": ValidationOutcome.FAILED,
        }.get(
            outcome_value,
            ValidationOutcome.INCONCLUSIVE,
        )
        errors = result.data.get("errors", [])
        failure_count = (
            len(errors)
            if isinstance(errors, list)
            else 1
        )

        if not result.success:
            outcome = ValidationOutcome.INCONCLUSIVE
            failure_count = 0

        return ValidationEvidence(
            tool_name=tool_name,
            execution_succeeded=result.success,
            outcome=outcome,
            scope=ValidationScope.TARGETED,
            purpose=ValidationPurpose.ACCEPTANCE,
            edit_revision=self.state.edit_revision,
            failed=(
                failure_count
                if outcome == ValidationOutcome.FAILED
                else 0
            ),
            failed_count=(
                failure_count
                if outcome == ValidationOutcome.FAILED
                else (
                    0
                    if outcome == ValidationOutcome.PASSED
                    else None
                )
            ),
            path=str(arguments.get("path", "")).strip(),
            summary=result.summary,
            details=dict(result.data),
        )

    def _from_run_command(
        self,
        *,
        arguments: dict,
        result: ToolResult,
    ) -> ValidationEvidence:
        """Normalize an explicitly labelled acceptance command."""

        command = str(
            arguments.get(
                "command",
                "",
            )
        ).strip()

        if not result.success:
            outcome = ValidationOutcome.INCONCLUSIVE
            execution_succeeded = False
            failed_count = None
        elif result.data.get("command_succeeded") is True:
            outcome = ValidationOutcome.PASSED
            execution_succeeded = True
            failed_count = 0
        elif result.data.get("command_succeeded") is False:
            outcome = ValidationOutcome.FAILED
            execution_succeeded = True
            failed_count = 1
        else:
            outcome = ValidationOutcome.INCONCLUSIVE
            execution_succeeded = True
            failed_count = None

        return ValidationEvidence(
            tool_name="run_command",
            execution_succeeded=execution_succeeded,
            outcome=outcome,
            scope=ValidationScope.TARGETED,
            purpose=ValidationPurpose.ACCEPTANCE,
            edit_revision=self.state.edit_revision,
            failed=(
                1
                if outcome == ValidationOutcome.FAILED
                else 0
            ),
            failed_count=failed_count,
            path=command,
            summary=result.summary,
        )

    # =========================================================
    # Record Evidence
    # =========================================================

    def _record_evidence(
        self,
        evidence: ValidationEvidence,
    ) -> None:
        """
        Update validation truth conservatively.

        A later contradictory result must invalidate an
        earlier green result for the same evidence category.

        Examples:

            acceptance PASS
            → acceptance FAIL
            → acceptance_passed = False

            full PASS
            → full FAIL
            → full_passed = False
        """

        self.state.latest_evidence = (
            evidence
        )

        self.state.evidence_history.append(evidence)
        if len(self.state.evidence_history) > 100:
            del self.state.evidence_history[:-100]
        if evidence.edit_revision == 0 and evidence.purpose == ValidationPurpose.REGRESSION:
            self.state.baseline_by_key[evidence.validation_key] = evidence

        self.state.evidence_sequence += 1

        passed = evidence.outcome == ValidationOutcome.PASSED and not evidence.unstable

        # =====================================================
        # Acceptance
        # =====================================================

        if (
            evidence.purpose
            == ValidationPurpose.ACCEPTANCE
        ):

            self.state.acceptance_passed = (
                passed
            )

            return

        # =====================================================
        # Regression
        # =====================================================

        if (
            evidence.scope
            == ValidationScope.TARGETED
        ):

            self.state.targeted_passed = (
                passed
            )

            # A known targeted regression failure contradicts
            # any older claim that the current revision is
            # fully regression-safe.
            if not passed:

                self.state.full_passed = False

            return

        if (
            evidence.scope
            == ValidationScope.FULL
        ):

            self.state.full_passed = (
                passed
            )

            return

        # Unknown regression evidence cannot establish safety.
        if not passed:

            self.state.full_passed = False

    def _mark_stability(self, evidence: ValidationEvidence) -> ValidationEvidence:
        comparable = [
            item for item in self.state.evidence_history
            if item.edit_revision == evidence.edit_revision
            and item.validation_key == evidence.validation_key
        ]
        if evidence.validation_key in self.state.unstable_keys:
            recent = comparable[-2:]
            if len(recent) == 2 and all(item.outcome == evidence.outcome for item in recent):
                self.state.unstable_keys.discard(evidence.validation_key)
                return evidence
            return replace(evidence, unstable=True)
        if comparable and any(item.outcome != evidence.outcome for item in comparable):
            self.state.unstable_keys.add(evidence.validation_key)
            return replace(evidence, unstable=True)
        return evidence

    def failure_delta(self, evidence: ValidationEvidence) -> FailureDelta:
        comparison = self.compare_baseline(evidence)
        if comparison is None:
            return FailureDelta.UNKNOWN
        if comparison.new:
            return FailureDelta.NEW_FAILURE
        if comparison.resolved:
            return FailureDelta.RESOLVED_FAILURE
        if comparison.persisting:
            return (
                FailureDelta.PRE_EXISTING_FAILURE
                if evidence.edit_revision > 0
                else FailureDelta.PERSISTING_FAILURE
            )
        return FailureDelta.UNKNOWN

    def compare_baseline(self, evidence: ValidationEvidence) -> FailureComparison | None:
        baseline = self.state.baseline_by_key.get(evidence.validation_key)
        if baseline is None:
            return None
        before = set(baseline.failure_ids)
        after = set(evidence.failure_ids)
        return FailureComparison(
            new=tuple(sorted(after - before)),
            resolved=tuple(sorted(before - after)),
            persisting=tuple(sorted(before & after)),
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

        current = (
            evidence
            or self.state.latest_evidence
        )

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

    # =========================================================
    # Normalize RunTests
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

        purpose = (
            self._validation_purpose(
                arguments.get(
                    "purpose",
                    "regression",
                )
            )
        )

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
                purpose=purpose,
                edit_revision=(
                    self.state
                    .edit_revision
                ),
                failed_count=None,
                path=path,
                summary=(
                    result.summary
                ),
                environment_failure=True,
                details=dict(result.data),
            )

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
        # Passed
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
                purpose=purpose,
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
                failure_ids=tuple(dict.fromkeys(tuple(result.data.get("failed_tests", ()) or ()) + tuple(result.data.get("failure_fingerprints", ()) or ()))),
                details=dict(result.data),
            )

        # =====================================================
        # Failed
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
                purpose=purpose,
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
                failure_ids=tuple(dict.fromkeys(tuple(result.data.get("failed_tests", ()) or ()) + tuple(result.data.get("failure_fingerprints", ()) or ()))),
                details=dict(result.data),
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
            purpose=purpose,
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
            failure_ids=tuple(dict.fromkeys(tuple(result.data.get("failed_tests", ()) or ()) + tuple(result.data.get("failure_fingerprints", ()) or ()))),
            details=dict(result.data),
        )

    # =========================================================
    # Scope
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
                ValidationScope.TARGETED
            )

        return (
            ValidationScope.UNKNOWN
        )

    # =========================================================
    # Purpose
    # =========================================================

    @staticmethod
    def _validation_purpose(
        value,
    ) -> ValidationPurpose:
        """
        Unknown purpose values degrade to regression.

        This is conservative:
        an invalid value can never fabricate acceptance
        evidence.
        """

        normalized = (
            str(value)
            .strip()
            .lower()
        )

        if (
            normalized
            == ValidationPurpose.ACCEPTANCE.value
        ):

            return (
                ValidationPurpose.ACCEPTANCE
            )

        return (
            ValidationPurpose.REGRESSION
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
