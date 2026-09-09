from pathlib import Path
from types import SimpleNamespace

from ..agent.editing import (
    CheckpointManager,
)
from ..agent.orchestration.validation_orchestrator import (
    apply_validation_evidence,
)
from ..agent.progress import (
    ProgressController,
)
from ..agent.progress import (
    RecoveryController,
)
from ..agent.editing import (
    RollbackEngine,
)
from ..agent.validation import (
    ValidationPipeline,
)
from ..agent.memory import (
    WorkingSummary,
)
from ..tools.results import (
    ToolResult,
)


def failed_result(
    failed: int,
) -> ToolResult:

    return ToolResult(
        success=True,
        summary=(
            f"{failed} failed."
        ),
        data={
            "tests_passed": False,
            "passed": 0,
            "failed": failed,
            "errors": 0,
            "skipped": 0,
        },
    )


def make_agent(
    tmp_path: Path,
):

    checkpoint_manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    return SimpleNamespace(
        validation_pipeline=(
            ValidationPipeline()
        ),
        checkpoint_manager=(
            checkpoint_manager
        ),
        rollback_engine=(
            RollbackEngine(
                workspace=tmp_path,
                checkpoint_manager=(
                    checkpoint_manager
                ),
            )
        ),
        progress=(
            ProgressController(
                max_same_tool_repeats=2,
                progress_window=6,
                max_validation_no_progress=2,
            )
        ),
        recovery=(
            RecoveryController()
        ),
        working_summary=(
            WorkingSummary(
                max_items=30
            )
        ),
        replan=lambda reason: {
            "replanned": False,
            "reason": reason,
        },
    )


# =============================================================
# Regression Causes Automatic Rollback
# =============================================================


def test_first_regressed_validation_does_not_roll_back_latest_edit(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    file_path.write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    agent = (
        make_agent(
            tmp_path
        )
    )

    # =========================================================
    # Revision 1
    # First repair still has 5 failing acceptance tests.
    # =========================================================

    agent.validation_pipeline.record_edit()

    first = (
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "tests/test_feature.py"
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
    # Prepare Revision 2
    # =========================================================

    checkpoint = (
        agent.checkpoint_manager
        .capture(
            path="demo.py",
            edit_revision=2,
        )
    )

    file_path.write_text(
        "value = 999\n",
        encoding="utf-8",
    )

    agent.checkpoint_manager.seal(
        checkpoint.checkpoint_id
    )

    revision = (
        agent.validation_pipeline
        .record_edit()
    )

    assert (
        revision
        == 2
    )

    # Same acceptance target becomes worse:
    # 5 failed -> 8 failed.
    second = (
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "tests/test_feature.py"
                ),
                "purpose": (
                    "acceptance"
                ),
            },
            result=(
                failed_result(
                    8
                )
            ),
        )
    )

    messages = []

    decision = apply_validation_evidence(
        agent=agent,
        evidence=second,
        messages=messages,
    )
    early_stop = decision.early_stop
    restart = decision.restart

    assert (
        early_stop
        is None
    )

    assert (
        restart
        is True
    )

    # A first regression is an intermediate state. Without semantic proof of
    # causality the Harness retains it for inspection/corrective repair.
    assert (
        file_path.read_text(
            encoding="utf-8"
        )
        == "value = 999\n"
    )

    assert (
        checkpoint.rolled_back
        is False
    )

    # Rollback creates a new monotonic revision.
    assert (
        agent.validation_pipeline
        .state
        .edit_revision
        == 2
    )

    # Old evidence is stale.
    assert (
        agent.validation_pipeline
        .state
        .acceptance_passed
        is False
    )

    assert (
        agent.validation_pipeline
        .state
        .full_passed
        is False
    )

    assert (
        messages
        == []
    )

    assert (
        "uncertain"
        in (
            decision.followup_message
            .lower()
        )
    )


# =============================================================
# Improvement Must NOT Roll Back
# =============================================================


def test_improved_validation_does_not_rollback(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    file_path.write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    agent = (
        make_agent(
            tmp_path
        )
    )

    agent.validation_pipeline.record_edit()

    first = (
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "tests/test_feature.py"
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

    checkpoint = (
        agent.checkpoint_manager
        .capture(
            path="demo.py",
            edit_revision=2,
        )
    )

    file_path.write_text(
        "value = 2\n",
        encoding="utf-8",
    )

    agent.checkpoint_manager.seal(
        checkpoint.checkpoint_id
    )

    agent.validation_pipeline.record_edit()

    second = (
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "tests/test_feature.py"
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

    decision = apply_validation_evidence(
        agent=agent,
        evidence=second,
        messages=[],
    )
    early_stop = decision.early_stop
    restart = decision.restart

    assert (
        early_stop
        is None
    )

    assert (
        restart
        is False
    )

    assert (
        file_path.read_text(
            encoding="utf-8"
        )
        == "value = 2\n"
    )

    assert (
        checkpoint.rolled_back
        is False
    )


# =============================================================
# Different Validation Targets Are Not Comparable
# =============================================================


def test_different_validation_targets_do_not_trigger_rollback(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    file_path.write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    agent = (
        make_agent(
            tmp_path
        )
    )

    agent.validation_pipeline.record_edit()

    acceptance = (
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "tests/test_feature.py"
                ),
                "purpose": (
                    "acceptance"
                ),
            },
            result=(
                failed_result(
                    1
                )
            ),
        )
    )

    apply_validation_evidence(
        agent=agent,
        evidence=acceptance,
        messages=[],
    )

    checkpoint = (
        agent.checkpoint_manager
        .capture(
            path="demo.py",
            edit_revision=2,
        )
    )

    file_path.write_text(
        "value = 2\n",
        encoding="utf-8",
    )

    agent.checkpoint_manager.seal(
        checkpoint.checkpoint_id
    )

    agent.validation_pipeline.record_edit()

    # Numerically 1 -> 5, but this is a DIFFERENT validation
    # series and must not be considered regression.
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
                failed_result(
                    5
                )
            ),
        )
    )

    decision = apply_validation_evidence(
        agent=agent,
        evidence=regression,
        messages=[],
    )
    early_stop = decision.early_stop
    restart = decision.restart

    assert (
        early_stop
        is None
    )

    assert (
        restart
        is False
    )

    assert (
        file_path.read_text(
            encoding="utf-8"
        )
        == "value = 2\n"
    )

    assert (
        checkpoint.rolled_back
        is False
    )

# =============================================================
# Same Revision Regression Must NOT Roll Back
# =============================================================


def test_same_revision_regression_does_not_trigger_rollback(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    file_path.write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    agent = (
        make_agent(
            tmp_path
        )
    )

    # =========================================================
    # Create Revision 1
    # =========================================================

    checkpoint = (
        agent.checkpoint_manager
        .capture(
            path="demo.py",
            edit_revision=1,
        )
    )

    file_path.write_text(
        "value = 2\n",
        encoding="utf-8",
    )

    agent.checkpoint_manager.seal(
        checkpoint.checkpoint_id
    )

    revision = (
        agent.validation_pipeline
        .record_edit()
    )

    assert (
        revision
        == 1
    )

    # =========================================================
    # First Validation
    # =========================================================

    first = (
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "tests/test_feature.py"
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
    # Second Validation
    #
    # IMPORTANT:
    # No edit occurred between the two test runs.
    #
    # 5 → 8 is numerically worse, but still revision 1.
    # Therefore rollback MUST NOT happen.
    # =========================================================

    second = (
        agent.validation_pipeline
        .observe(
            tool_name="run_tests",
            arguments={
                "path": (
                    "tests/test_feature.py"
                ),
                "purpose": (
                    "acceptance"
                ),
            },
            result=(
                failed_result(
                    8
                )
            ),
        )
    )

    messages = []

    decision = apply_validation_evidence(
        agent=agent,
        evidence=second,
        messages=messages,
    )
    early_stop = decision.early_stop
    restart = decision.restart

    assert (
        early_stop
        is None
    )

    # =========================================================
    # No Rollback
    # =========================================================

    assert (
        checkpoint.rolled_back
        is False
    )

    assert (
        file_path.read_text(
            encoding="utf-8"
        )
        == "value = 2\n"
    )

    # No rollback revision was created.
    assert (
        agent.validation_pipeline
        .state
        .edit_revision
        == 1
    )
