from types import SimpleNamespace

from ..agent.completion import (
    CompletionStatus,
)
from ..agent.loop import (
    EDIT_TOOL_NAMES,
    apply_validation_evidence,
    can_complete_edit_task,
    evaluate_completion,
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


# =============================================================
# Fake Recovery
# =============================================================


class FakeRecovery:

    def __init__(
        self,
    ):

        self.progress_marks = 0

        self.recovery_calls = 0

    def mark_progress(
        self,
    ) -> None:

        self.progress_marks += 1

    def recover(
        self,
        reason: str,
        replan_callback,
    ):

        self.recovery_calls += 1

        return (
            "Recovery requested.",
            True,
        )


# =============================================================
# Fake Agent
# =============================================================


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
            "reason": reason,
        },
    )


# =============================================================
# ToolResult Helpers
# =============================================================


def passed_result(
    count: int = 1,
) -> ToolResult:

    return ToolResult(
        success=True,
        summary=(
            f"{count} passed."
        ),
        data={
            "tests_passed": True,
            "passed": count,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        },
    )


def failed_result(
    failed: int,
    *,
    passed: int = 0,
) -> ToolResult:

    return ToolResult(
        success=True,
        summary=(
            f"{passed} passed, "
            f"{failed} failed."
        ),
        data={
            "tests_passed": False,
            "passed": passed,
            "failed": failed,
            "errors": 0,
            "skipped": 0,
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
# No Edit
# =============================================================


def test_completion_gate_rejects_task_without_edit():

    agent = (
        make_agent()
    )

    decision = (
        evaluate_completion(
            agent
        )
    )

    assert (
        decision.status
        == CompletionStatus.NOT_READY
    )

    assert (
        decision.can_complete
        is False
    )

    assert (
        can_complete_edit_task(
            agent
        )
        is False
    )


# =============================================================
# Full Regression Alone
# =============================================================


def test_full_regression_alone_does_not_complete_task():

    agent = (
        make_agent()
    )

    agent.validation_pipeline.record_edit()

    evidence = (
        agent.validation_pipeline
        .observe(
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
        agent.validation_pipeline
        .next_action(
            evidence
        )
        == (
            ValidationNextAction
            .RUN_ACCEPTANCE_VALIDATION
        )
    )

    decision = (
        evaluate_completion(
            agent
        )
    )

    assert (
        decision.status
        == (
            CompletionStatus
            .NEEDS_ACCEPTANCE
        )
    )

    assert (
        decision.can_complete
        is False
    )

    assert (
        can_complete_edit_task(
            agent
        )
        is False
    )


# =============================================================
# Regression Pass Forces Acceptance
# =============================================================


def test_regression_pass_forces_acceptance_validation():

    agent = (
        make_agent()
    )

    agent.validation_pipeline.record_edit()

    evidence = (
        agent.validation_pipeline
        .observe(
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
        len(messages)
        == 1
    )

    message = (
        messages[0][
            "content"
        ]
        .lower()
    )

    assert (
        "acceptance"
        in message
    )

    assert (
        "purpose='acceptance'"
        in message
    )

    assert (
        can_complete_edit_task(
            agent
        )
        is False
    )


# =============================================================
# Acceptance Alone
# =============================================================


def test_acceptance_alone_does_not_complete_task():

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
        agent.validation_pipeline
        .next_action(
            evidence
        )
        == (
            ValidationNextAction
            .RUN_FULL_VALIDATION
        )
    )

    decision = (
        evaluate_completion(
            agent
        )
    )

    assert (
        decision.status
        == (
            CompletionStatus
            .NEEDS_FULL_VALIDATION
        )
    )

    assert (
        decision.can_complete
        is False
    )


# =============================================================
# Acceptance Pass Forces Full Regression
# =============================================================


def test_acceptance_pass_forces_full_regression():

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
                    "test_feature.py"
                ),
                "purpose": (
                    "acceptance"
                ),
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
        len(messages)
        == 1
    )

    message = (
        messages[0][
            "content"
        ]
        .lower()
    )

    assert (
        "full regression"
        in message
    )

    assert (
        "purpose='regression'"
        in message
    )

    assert (
        can_complete_edit_task(
            agent
        )
        is False
    )


# =============================================================
# Acceptance + Full Regression
# =============================================================


def test_acceptance_then_full_regression_opens_completion_gate():

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

    acceptance = (
        agent.validation_pipeline
        .observe(
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
                    4
                )
            ),
        )
    )

    assert (
        agent.validation_pipeline
        .next_action(
            acceptance
        )
        == (
            ValidationNextAction
            .RUN_FULL_VALIDATION
        )
    )

    regression = (
        agent.validation_pipeline
        .observe(
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
        agent.validation_pipeline
        .next_action(
            regression
        )
        == (
            ValidationNextAction
            .TASK_VALIDATED
        )
    )

    messages = []

    (
        early_stop,
        restart,
    ) = (
        apply_validation_evidence(
            agent=agent,
            evidence=regression,
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

    decision = (
        evaluate_completion(
            agent
        )
    )

    assert (
        decision.status
        == CompletionStatus.READY
    )

    assert (
        decision.can_complete
        is True
    )

    assert (
        decision.edit_revision
        == 1
    )

    assert (
        can_complete_edit_task(
            agent
        )
        is True
    )


# =============================================================
# Full Regression + Acceptance
# =============================================================


def test_full_regression_then_acceptance_also_opens_gate():

    agent = (
        make_agent()
    )

    agent.validation_pipeline.record_edit()

    agent.validation_pipeline.observe(
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

    acceptance = (
        agent.validation_pipeline
        .observe(
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
        agent.validation_pipeline
        .next_action(
            acceptance
        )
        == (
            ValidationNextAction
            .TASK_VALIDATED
        )
    )

    assert (
        can_complete_edit_task(
            agent
        )
        is True
    )


# =============================================================
# New Edit Invalidates Completion
# =============================================================


def test_new_edit_closes_completion_gate_again():

    agent = (
        make_agent()
    )

    agent.validation_pipeline.record_edit()

    agent.validation_pipeline.observe(
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

    agent.validation_pipeline.observe(
        tool_name="run_tests",
        arguments={
            "path": ".",
            "purpose": (
                "regression"
            ),
        },
        result=(
            passed_result(
                30
            )
        ),
    )

    assert (
        can_complete_edit_task(
            agent
        )
        is True
    )

    # =========================================================
    # New edit creates revision 2 and invalidates all
    # previous completion evidence.
    # =========================================================

    revision = (
        agent.validation_pipeline
        .record_edit()
    )

    assert (
        revision
        == 2
    )

    assert (
        can_complete_edit_task(
            agent
        )
        is False
    )

    decision = (
        evaluate_completion(
            agent
        )
    )

    assert (
        decision.status
        == (
            CompletionStatus
            .NEEDS_ACCEPTANCE
        )
    )


# =============================================================
# Failed Validation
# =============================================================


def test_failed_validation_does_not_restart_when_not_stalled():

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
                    "test_feature.py"
                ),
                "purpose": (
                    "acceptance"
                ),
            },
            result=(
                failed_result(
                    3
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
        agent.progress
        .last_validation_failed_count
        == 3
    )

    assert (
        can_complete_edit_task(
            agent
        )
        is False
    )


# =============================================================
# Validation Improvement
# =============================================================


def test_validation_improvement_marks_recovery_progress():

    agent = (
        make_agent()
    )

    agent.validation_pipeline.record_edit()

    first = (
        agent.validation_pipeline
        .observe(
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
                    5
                )
            ),
        )
    )

    apply_validation_evidence(
        agent=agent,
        evidence=first,
        messages=[],
    )

    # =========================================================
    # Repair edit.
    #
    # ValidationPipeline revision changes, while
    # ProgressController intentionally keeps the failure
    # trend so it can recognize 5 -> 3 as progress.
    # =========================================================

    agent.validation_pipeline.record_edit()

    second = (
        agent.validation_pipeline
        .observe(
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
            messages=[],
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
        len(messages)
        == 1
    )

    assert (
        "inconclusive"
        in (
            messages[0][
                "content"
            ]
            .lower()
        )
    )

    assert (
        can_complete_edit_task(
            agent
        )
        is False
    )


# =============================================================
# Full Regression Without Edit
# =============================================================


def test_full_regression_without_edit_does_not_open_gate():

    agent = (
        make_agent()
    )

    evidence = (
        agent.validation_pipeline
        .observe(
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
        agent.validation_pipeline
        .next_action(
            evidence
        )
        == ValidationNextAction.NONE
    )

    assert (
        can_complete_edit_task(
            agent
        )
        is False
    )

    decision = (
        evaluate_completion(
            agent
        )
    )

    assert (
        decision.status
        == CompletionStatus.NOT_READY
    )