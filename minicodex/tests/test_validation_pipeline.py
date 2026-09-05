from ..agent.validation import (
    ValidationNextAction,
    ValidationOutcome,
    ValidationPipeline,
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


# =============================================================
# Full Validation
# =============================================================


def test_full_suite_passed():

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
                passed_result(
                    10
                )
            ),
        )
    )

    assert evidence is not None

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
        == ValidationScope.FULL
    )

    assert (
        evidence.edit_revision
        == 1
    )

    assert (
        pipeline
        .current_edit_validated()
        is True
    )

    assert (
        pipeline.next_action()
        == (
            ValidationNextAction
            .TASK_VALIDATED
        )
    )


# =============================================================
# Targeted Validation Escalation
# =============================================================


def test_targeted_pass_requires_full_validation():

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
                    "test_replace_symbol.py"
                )
            },
            result=(
                passed_result(
                    3
                )
            ),
        )
    )

    assert (
        evidence.scope
        == ValidationScope.TARGETED
    )

    assert (
        evidence.outcome
        == ValidationOutcome.PASSED
    )

    assert (
        pipeline
        .requires_full_validation()
        is True
    )

    assert (
        pipeline
        .current_edit_validated()
        is False
    )

    assert (
        pipeline.next_action()
        == (
            ValidationNextAction
            .RUN_FULL_VALIDATION
        )
    )


# =============================================================
# Targeted → Full
# =============================================================


def test_targeted_then_full_pass_validates_edit():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    targeted = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "minicodex/tests/"
                    "test_demo.py"
                )
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
            targeted
        )
        == (
            ValidationNextAction
            .RUN_FULL_VALIDATION
        )
    )

    full = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": "."
            },
            result=(
                passed_result(
                    20
                )
            ),
        )
    )

    assert (
        full.scope
        == ValidationScope.FULL
    )

    assert (
        pipeline
        .requires_full_validation()
        is False
    )

    assert (
        pipeline
        .current_edit_validated()
        is True
    )

    assert (
        pipeline.next_action(
            full
        )
        == (
            ValidationNextAction
            .TASK_VALIDATED
        )
    )


# =============================================================
# New Edit Invalidates Old Evidence
# =============================================================


def test_new_edit_invalidates_previous_full_validation():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    pipeline.observe(
        tool_name="run_tests",
        arguments={
            "path": "."
        },
        result=(
            passed_result(
                10
            )
        ),
    )

    assert (
        pipeline
        .current_edit_validated()
        is True
    )

    assert (
        pipeline.state.edit_revision
        == 1
    )

    # =========================================================
    # New code change
    # =========================================================

    pipeline.record_edit()

    assert (
        pipeline.state.edit_revision
        == 2
    )

    assert (
        pipeline.state.targeted_passed
        is False
    )

    assert (
        pipeline.state.full_passed
        is False
    )

    assert (
        pipeline.state.latest_evidence
        is None
    )

    assert (
        pipeline
        .current_edit_validated()
        is False
    )


# =============================================================
# Failure
# =============================================================


def test_failed_validation_requests_fix():

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
        pipeline.next_action()
        == (
            ValidationNextAction
            .FIX_FAILURE
        )
    )

    assert (
        pipeline
        .current_edit_validated()
        is False
    )


# =============================================================
# Errors Count As Validation Failures
# =============================================================


def test_errors_count_as_failures():

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
# Tool Failure Is Inconclusive
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
                "path": "."
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
        pipeline.next_action()
        == (
            ValidationNextAction
            .INVESTIGATE_INCONCLUSIVE
        )
    )


# =============================================================
# Parser Cannot Reach Conclusion
# =============================================================


def test_unrecognized_result_is_inconclusive():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    result = ToolResult(
        success=True,
        summary=(
            "pytest exited unexpectedly."
        ),
        data={
            "tests_passed": False,
            "passed": 0,
            "failed": 0,
            "errors": 0,
        },
    )

    evidence = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": "."
            },
            result=result,
        )
    )

    assert (
        evidence.outcome
        == (
            ValidationOutcome
            .INCONCLUSIVE
        )
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
# Revision Attached To Evidence
# =============================================================


def test_evidence_is_bound_to_current_edit_revision():

    pipeline = (
        ValidationPipeline()
    )

    pipeline.record_edit()

    first = (
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
        first.edit_revision
        == 1
    )

    pipeline.record_edit()

    second = (
        pipeline.observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "minicodex/tests/"
                    "test_demo.py"
                )
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
            "path": "."
        },
        result=(
            passed_result()
        ),
    )

    pipeline.reset()

    assert (
        pipeline.state.edit_revision
        == 0
    )

    assert (
        pipeline.state.has_edit
        is False
    )

    assert (
        pipeline.state.targeted_passed
        is False
    )

    assert (
        pipeline.state.full_passed
        is False
    )

    assert (
        pipeline.state.latest_evidence
        is None
    )