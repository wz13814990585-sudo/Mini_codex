from ..agent.validation import (
    ValidationNextAction,
    ValidationOutcome,
    ValidationPipeline,
    ValidationPurpose,
    ValidationScope,
)
from ..tools.results import (
    ToolResult,
)


# =============================================================
# Helpers
# =============================================================


def passed_result(
    passed: int = 1,
) -> ToolResult:

    return ToolResult(
        success=True,
        summary=(
            f"{passed} passed."
        ),
        data={
            "tests_passed": True,
            "passed": passed,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        },
    )


def failed_result(
    *,
    passed: int = 0,
    failed: int = 1,
    errors: int = 0,
) -> ToolResult:

    return ToolResult(
        success=True,
        summary=(
            f"{passed} passed, "
            f"{failed} failed, "
            f"{errors} errors."
        ),
        data={
            "tests_passed": False,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": 0,
        },
    )


def inconclusive_result() -> ToolResult:

    return ToolResult(
        success=True,
        summary=(
            "pytest exited unexpectedly."
        ),
        data={
            "tests_passed": False,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        },
    )


# =============================================================
# Acceptance Evidence
# =============================================================


def test_acceptance_pass_is_recorded():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    evidence = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "minicodex/tests/"
                    "test_feature.py"
                ),
                "purpose": (
                    "acceptance"
                ),
            },
            result=(
                passed_result(
                    3
                )
            ),
        )
    )

    assert (
        evidence
        is not None
    )

    assert (
        evidence.execution_succeeded
        is True
    )

    assert (
        evidence.outcome
        == ValidationOutcome.PASSED
    )

    assert (
        evidence.scope
        == ValidationScope.TARGETED
    )

    assert (
        evidence.purpose
        == ValidationPurpose.ACCEPTANCE
    )

    assert (
        evidence.edit_revision
        == 1
    )

    assert (
        pipeline.state
        .acceptance_passed
        is True
    )

    assert (
        pipeline.state
        .full_passed
        is False
    )

    assert (
        pipeline
        .current_acceptance_passed()
        is True
    )

    assert (
        pipeline
        .current_edit_validated()
        is False
    )


# =============================================================
# Acceptance Pass Requires Full Regression
# =============================================================


def test_acceptance_pass_requires_full_regression():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    evidence = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "minicodex/tests/"
                    "test_feature.py"
                ),
                "purpose": (
                    "acceptance"
                ),
            },
            result=(
                passed_result(
                    2
                )
            ),
        )
    )

    assert (
        pipeline.next_action(
            evidence
        )
        == (
            ValidationNextAction
            .RUN_FULL_VALIDATION
        )
    )

    assert (
        pipeline
        .requires_full_validation()
        is True
    )

    assert (
        pipeline
        .requires_acceptance_validation()
        is False
    )


# =============================================================
# Full Regression Alone Is Not Completion
# =============================================================


def test_full_regression_without_acceptance_requests_acceptance():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    evidence = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": ".",
                "purpose": (
                    "regression"
                ),
            },
            result=(
                passed_result(
                    100
                )
            ),
        )
    )

    assert (
        evidence.scope
        == ValidationScope.FULL
    )

    assert (
        evidence.purpose
        == ValidationPurpose.REGRESSION
    )

    assert (
        pipeline.state
        .full_passed
        is True
    )

    assert (
        pipeline.state
        .acceptance_passed
        is False
    )

    # Regression-level code validation is true.
    assert (
        pipeline
        .current_edit_validated()
        is True
    )

    # But task completion evidence is incomplete.
    assert (
        pipeline
        .current_acceptance_passed()
        is False
    )

    assert (
        pipeline.next_action(
            evidence
        )
        == (
            ValidationNextAction
            .RUN_ACCEPTANCE_VALIDATION
        )
    )


# =============================================================
# Targeted Regression Alone Is Also Not Acceptance
# =============================================================


def test_targeted_regression_does_not_count_as_acceptance():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    evidence = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "minicodex/tests/"
                    "test_existing_behavior.py"
                ),
                "purpose": (
                    "regression"
                ),
            },
            result=(
                passed_result(
                    4
                )
            ),
        )
    )

    assert (
        evidence.scope
        == ValidationScope.TARGETED
    )

    assert (
        evidence.purpose
        == ValidationPurpose.REGRESSION
    )

    assert (
        pipeline.state
        .targeted_passed
        is True
    )

    assert (
        pipeline.state
        .acceptance_passed
        is False
    )

    assert (
        pipeline.state
        .full_passed
        is False
    )

    assert (
        pipeline.next_action(
            evidence
        )
        == (
            ValidationNextAction
            .RUN_ACCEPTANCE_VALIDATION
        )
    )


# =============================================================
# Acceptance → Full Regression
# =============================================================


def test_acceptance_then_full_regression_validates_task_evidence():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    acceptance = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "minicodex/tests/"
                    "test_feature.py"
                ),
                "purpose": (
                    "acceptance"
                ),
            },
            result=(
                passed_result(
                    2
                )
            ),
        )
    )

    assert (
        pipeline.next_action(
            acceptance
        )
        == (
            ValidationNextAction
            .RUN_FULL_VALIDATION
        )
    )

    regression = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": ".",
                "purpose": (
                    "regression"
                ),
            },
            result=(
                passed_result(
                    100
                )
            ),
        )
    )

    assert (
        pipeline.state
        .acceptance_passed
        is True
    )

    assert (
        pipeline.state
        .full_passed
        is True
    )

    assert (
        pipeline.next_action(
            regression
        )
        == (
            ValidationNextAction
            .TASK_VALIDATED
        )
    )


# =============================================================
# Full Regression → Acceptance
# =============================================================


def test_full_regression_then_acceptance_also_validates_task():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    regression = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": ".",
                "purpose": (
                    "regression"
                ),
            },
            result=(
                passed_result(
                    50
                )
            ),
        )
    )

    assert (
        pipeline.next_action(
            regression
        )
        == (
            ValidationNextAction
            .RUN_ACCEPTANCE_VALIDATION
        )
    )

    acceptance = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "minicodex/tests/"
                    "test_feature.py"
                ),
                "purpose": (
                    "acceptance"
                ),
            },
            result=(
                passed_result(
                    1
                )
            ),
        )
    )

    assert (
        pipeline.next_action(
            acceptance
        )
        == (
            ValidationNextAction
            .TASK_VALIDATED
        )
    )


# =============================================================
# New Edit Invalidates Evidence
# =============================================================


def test_new_edit_invalidates_acceptance_and_regression():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    pipeline.observe(
        tool_name="run_tests",
        arguments={
            "path": (
                "minicodex/tests/"
                "test_feature.py"
            ),
            "purpose": (
                "acceptance"
            ),
        },
        result=(
            passed_result(
                1
            )
        ),
    )

    pipeline.observe(
        tool_name="run_tests",
        arguments={
            "path": ".",
            "purpose": (
                "regression"
            ),
        },
        result=(
            passed_result(
                20
            )
        ),
    )

    assert (
        pipeline.state
        .acceptance_passed
        is True
    )

    assert (
        pipeline.state
        .full_passed
        is True
    )

    assert (
        pipeline.state
        .edit_revision
        == 1
    )

    # =========================================================
    # New code revision.
    # =========================================================

    revision = (
        pipeline.record_edit()
    )

    assert (
        revision
        == 2
    )

    assert (
        pipeline.state
        .targeted_passed
        is False
    )

    assert (
        pipeline.state
        .acceptance_passed
        is False
    )

    assert (
        pipeline.state
        .full_passed
        is False
    )

    assert (
        pipeline.state
        .latest_evidence
        is None
    )

    assert (
        pipeline
        .current_edit_validated()
        is False
    )

    assert (
        pipeline
        .current_acceptance_passed()
        is False
    )


# =============================================================
# Acceptance Failure
# =============================================================


def test_acceptance_failure_requests_fix():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    evidence = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "minicodex/tests/"
                    "test_feature.py"
                ),
                "purpose": (
                    "acceptance"
                ),
            },
            result=(
                failed_result(
                    failed=2
                )
            ),
        )
    )

    assert (
        evidence.outcome
        == ValidationOutcome.FAILED
    )

    assert (
        evidence.failed_count
        == 2
    )

    assert (
        pipeline.state
        .acceptance_passed
        is False
    )

    assert (
        pipeline.next_action(
            evidence
        )
        == (
            ValidationNextAction
            .FIX_FAILURE
        )
    )


# =============================================================
# Regression Failure
# =============================================================


def test_regression_failure_requests_fix():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    evidence = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": ".",
                "purpose": (
                    "regression"
                ),
            },
            result=(
                failed_result(
                    passed=8,
                    failed=2,
                )
            ),
        )
    )

    assert (
        evidence.outcome
        == ValidationOutcome.FAILED
    )

    assert (
        evidence.failed_count
        == 2
    )

    assert (
        pipeline.state
        .full_passed
        is False
    )

    assert (
        pipeline.next_action(
            evidence
        )
        == (
            ValidationNextAction
            .FIX_FAILURE
        )
    )


# =============================================================
# Errors Count As Failures
# =============================================================


def test_validation_errors_count_as_failures():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    evidence = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": ".",
                "purpose": (
                    "regression"
                ),
            },
            result=(
                failed_result(
                    passed=2,
                    failed=0,
                    errors=1,
                )
            ),
        )
    )

    assert (
        evidence.outcome
        == ValidationOutcome.FAILED
    )

    assert (
        evidence.failed_count
        == 1
    )


# =============================================================
# Tool Execution Failure
# =============================================================


def test_tool_execution_failure_is_inconclusive():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    result = ToolResult(
        success=False,
        summary=(
            "Tests timed out."
        ),
        data={
            "timed_out": True,
        },
        error=(
            "pytest execution timed out"
        ),
    )

    evidence = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "minicodex/tests/"
                    "test_feature.py"
                ),
                "purpose": (
                    "acceptance"
                ),
            },
            result=result,
        )
    )

    assert (
        evidence.execution_succeeded
        is False
    )

    assert (
        evidence.outcome
        == (
            ValidationOutcome
            .INCONCLUSIVE
        )
    )

    assert (
        evidence.failed_count
        is None
    )

    assert (
        pipeline.state
        .acceptance_passed
        is False
    )

    assert (
        pipeline.next_action(
            evidence
        )
        == (
            ValidationNextAction
            .INVESTIGATE_INCONCLUSIVE
        )
    )


# =============================================================
# Parsed Result Still Inconclusive
# =============================================================


def test_unrecognized_test_result_is_inconclusive():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    evidence = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": ".",
                "purpose": (
                    "regression"
                ),
            },
            result=(
                inconclusive_result()
            ),
        )
    )

    assert (
        evidence.outcome
        == (
            ValidationOutcome
            .INCONCLUSIVE
        )
    )

    assert (
        pipeline.state
        .full_passed
        is False
    )


# =============================================================
# Default Purpose
# =============================================================


def test_default_validation_purpose_is_regression():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    evidence = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": "."
            },
            result=(
                passed_result()
            ),
        )
    )

    assert (
        evidence.purpose
        == ValidationPurpose.REGRESSION
    )


# =============================================================
# Revision Attached To Evidence
# =============================================================


def test_evidence_is_bound_to_current_revision():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    first = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "minicodex/tests/"
                    "test_feature.py"
                ),
                "purpose": (
                    "acceptance"
                ),
            },
            result=(
                passed_result()
            ),
        )
    )

    assert (
        first.edit_revision
        == 1
    )

    pipeline.record_edit()

    second = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": ".",
                "purpose": (
                    "regression"
                ),
            },
            result=(
                passed_result()
            ),
        )
    )

    assert (
        second.edit_revision
        == 2
    )


# =============================================================
# No Edit
# =============================================================


def test_validation_without_edit_does_not_validate_task():

    pipeline = (
        ValidationPipeline()
    )

    evidence = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": ".",
                "purpose": (
                    "regression"
                ),
            },
            result=(
                passed_result(
                    20
                )
            ),
        )
    )

    assert (
        evidence.outcome
        == ValidationOutcome.PASSED
    )

    assert (
        pipeline.state
        .has_edit
        is False
    )

    assert (
        pipeline.next_action(
            evidence
        )
        == ValidationNextAction.NONE
    )


# =============================================================
# Non Validation Tool
# =============================================================


def test_non_validation_tool_returns_none():

    pipeline = (
        ValidationPipeline()
    )

    result = ToolResult(
        success=True,
        summary=(
            "File read."
        ),
        data={},
    )

    evidence = (
        pipeline.observe(
            tool_name="read_file",
            arguments={},
            result=result,
        )
    )

    assert (
        evidence
        is None
    )


# =============================================================
# Reset
# =============================================================


def test_validation_pipeline_reset():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    pipeline.observe(
        tool_name="run_tests",
        arguments={
            "path": (
                "minicodex/tests/"
                "test_feature.py"
            ),
            "purpose": (
                "acceptance"
            ),
        },
        result=(
            passed_result()
        ),
    )

    pipeline.observe(
        tool_name="run_tests",
        arguments={
            "path": ".",
            "purpose": (
                "regression"
            ),
        },
        result=(
            passed_result()
        ),
    )

    pipeline.reset()

    assert (
        pipeline.state
        .edit_revision
        == 0
    )

    assert (
        pipeline.state
        .has_edit
        is False
    )

    assert (
        pipeline.state
        .targeted_passed
        is False
    )

    assert (
        pipeline.state
        .acceptance_passed
        is False
    )

    assert (
        pipeline.state
        .full_passed
        is False
    )

    assert (
        pipeline.state
        .latest_evidence
        is None
    )