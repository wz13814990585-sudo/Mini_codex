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
    failed: int = 1,
    *,
    passed: int = 0,
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

from types import SimpleNamespace

from ..agent.loop import (
    EDIT_TOOL_NAMES,
    apply_validation_evidence,
    has_validated_edit,
)
from ..agent.progress import (
    ProgressController,
)
from ..agent.validation import (
    ValidationNextAction,
    ValidationPipeline,
)
from ..tools.results import (
    ToolResult,
)


class FakeRecovery:

    def __init__(
        self,
    ):
        self.progress_marks = 0

    def mark_progress(
        self,
    ) -> None:

        self.progress_marks += 1

    def recover(
        self,
        reason: str,
        replan_callback,
    ):

        return (
            "Recovery requested.",
            True,
        )


def make_agent():

    return SimpleNamespace(
        validation_pipeline=(
            ValidationPipeline()
        ),
        progress=(
            ProgressController(
                max_same_tool_repeats=2,
                progress_window=6,
                max_validation_no_progress=2,
            )
        ),
        recovery=(
            FakeRecovery()
        ),
        replan=lambda reason: {
            "replanned": False,
        },
    )


# =============================================================
# Edit Tool Classification
# =============================================================


def test_all_stage8_edit_tools_are_classified():

    assert (
        EDIT_TOOL_NAMES
        == {
            "patch_file",
            "replace_lines",
            "replace_symbol",
            "write_file",
        }
    )


# =============================================================
# Full Validation Required
# =============================================================


def test_targeted_pass_forces_full_validation():

    agent = (
        make_agent()
    )

    agent.validation_pipeline.record_edit()

    evidence = (
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "minicodex/tests/"
                    "test_replace_symbol.py"
                )
            },
            result=(
                passed_result(
                    5
                )
            ),
        )
    )

    messages = []

    (
        early_stop,
        restart,
    ) = (
        apply_validation_evidence(
            agent=agent,
            evidence=evidence,
            messages=messages,
        )
    )

    assert (
        early_stop
        is None
    )

    assert (
        restart
        is True
    )

    assert (
        agent.validation_pipeline
        .next_action(
            evidence
        )
        == (
            ValidationNextAction
            .RUN_FULL_VALIDATION
        )
    )

    assert (
        has_validated_edit(
            agent
        )
        is False
    )

    assert (
        len(messages)
        == 1
    )

    assert (
        "full validation"
        in (
            messages[0][
                "content"
            ].lower()
        )
    )


# =============================================================
# Full PASS Validates Current Revision
# =============================================================


def test_full_pass_validates_current_edit():

    agent = (
        make_agent()
    )

    revision = (
        agent.validation_pipeline
        .record_edit()
    )

    assert (
        revision
        == 1
    )

    evidence = (
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": "."
            },
            result=(
                passed_result(
                    100
                )
            ),
        )
    )

    messages = []

    (
        early_stop,
        restart,
    ) = (
        apply_validation_evidence(
            agent=agent,
            evidence=evidence,
            messages=messages,
        )
    )

    assert (
        early_stop
        is None
    )

    assert (
        restart
        is False
    )

    assert (
        has_validated_edit(
            agent
        )
        is True
    )


# =============================================================
# New Edit Invalidates Full PASS
# =============================================================


def test_new_edit_invalidates_completion_evidence():

    agent = (
        make_agent()
    )

    agent.validation_pipeline.record_edit()

    agent.validation_pipeline.observe(
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

    assert (
        has_validated_edit(
            agent
        )
        is True
    )

    agent.validation_pipeline.record_edit()

    assert (
        has_validated_edit(
            agent
        )
        is False
    )

    assert (
        agent.validation_pipeline
        .state
        .edit_revision
        == 2
    )


# =============================================================
# Failure Uses Progress Trend
# =============================================================


def test_failed_validation_tracks_progress():

    agent = (
        make_agent()
    )

    agent.validation_pipeline.record_edit()

    first = (
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": "."
            },
            result=(
                failed_result(
                    5
                )
            ),
        )
    )

    messages = []

    (
        early_stop,
        restart,
    ) = (
        apply_validation_evidence(
            agent=agent,
            evidence=first,
            messages=messages,
        )
    )

    assert (
        early_stop
        is None
    )

    assert (
        restart
        is False
    )

    assert (
        agent.progress
        .last_validation_failed_count
        == 5
    )

    # =========================================================
    # Repair edit
    # =========================================================

    agent.validation_pipeline.record_edit()

    second = (
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": "."
            },
            result=(
                failed_result(
                    3
                )
            ),
        )
    )

    (
        early_stop,
        restart,
    ) = (
        apply_validation_evidence(
            agent=agent,
            evidence=second,
            messages=messages,
        )
    )

    assert (
        early_stop
        is None
    )

    assert (
        restart
        is False
    )

    assert (
        agent.progress
        .last_validation_failed_count
        == 3
    )

    assert (
        agent.recovery
        .progress_marks
        == 1
    )


# =============================================================
# Inconclusive Validation
# =============================================================


def test_inconclusive_validation_forces_investigation():

    agent = (
        make_agent()
    )

    agent.validation_pipeline.record_edit()

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
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": "."
            },
            result=result,
        )
    )

    messages = []

    (
        early_stop,
        restart,
    ) = (
        apply_validation_evidence(
            agent=agent,
            evidence=evidence,
            messages=messages,
        )
    )

    assert (
        early_stop
        is None
    )

    assert (
        restart
        is True
    )

    assert (
        has_validated_edit(
            agent
        )
        is False
    )

    assert (
        "inconclusive"
        in (
            messages[0][
                "content"
            ].lower()
        )
    )


# =============================================================
# Full Pass Without Edit Is Not Task Completion
# =============================================================


def test_full_pass_without_edit_does_not_validate_task():

    agent = (
        make_agent()
    )

    evidence = (
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": "."
            },
            result=(
                passed_result(
                    50
                )
            ),
        )
    )

    assert (
        agent.validation_pipeline
        .next_action(
            evidence
        )
        == (
            ValidationNextAction.NONE
        )
    )

    assert (
        has_validated_edit(
            agent
        )
        is False
    )