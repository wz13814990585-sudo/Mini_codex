from pathlib import Path

from ..agent.checkpoint import (
    CheckpointManager,
)
from ..agent.rollback import (
    RollbackEngine,
)


# =============================================================
# Existing File Rollback
# =============================================================


def test_rollback_restores_existing_file(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.txt"
    )

    file_path.write_text(
        "before",
        encoding="utf-8",
    )

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    checkpoint = (
        manager.capture(
            path="demo.txt",
            edit_revision=1,
        )
    )

    file_path.write_text(
        "after",
        encoding="utf-8",
    )

    manager.seal(
        checkpoint.checkpoint_id
    )

    engine = (
        RollbackEngine(
            workspace=tmp_path,
            checkpoint_manager=(
                manager
            ),
        )
    )

    result = (
        engine.rollback(
            checkpoint
            .checkpoint_id
        )
    )

    assert (
        result.success
        is True
    )

    assert (
        file_path.read_text(
            encoding="utf-8"
        )
        == "before"
    )

    assert (
        checkpoint.rolled_back
        is True
    )


# =============================================================
# New File Rollback
# =============================================================


def test_rollback_removes_newly_created_file(
    tmp_path: Path,
):

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    checkpoint = (
        manager.capture(
            path="new_file.txt",
            edit_revision=1,
        )
    )

    file_path = (
        tmp_path
        / "new_file.txt"
    )

    file_path.write_text(
        "created",
        encoding="utf-8",
    )

    manager.seal(
        checkpoint.checkpoint_id
    )

    engine = (
        RollbackEngine(
            workspace=tmp_path,
            checkpoint_manager=(
                manager
            ),
        )
    )

    result = (
        engine.rollback(
            checkpoint
            .checkpoint_id
        )
    )

    assert (
        result.success
        is True
    )

    assert (
        file_path.exists()
        is False
    )

    assert (
        result.data[
            "removed_created_file"
        ]
        is True
    )


# =============================================================
# Stale Rollback
# =============================================================


def test_rollback_rejects_newer_file_changes(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.txt"
    )

    file_path.write_text(
        "before",
        encoding="utf-8",
    )

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    checkpoint = (
        manager.capture(
            path="demo.txt",
            edit_revision=1,
        )
    )

    file_path.write_text(
        "revision-1",
        encoding="utf-8",
    )

    manager.seal(
        checkpoint.checkpoint_id
    )

    # A later edit happened.
    file_path.write_text(
        "revision-2",
        encoding="utf-8",
    )

    engine = (
        RollbackEngine(
            workspace=tmp_path,
            checkpoint_manager=(
                manager
            ),
        )
    )

    result = (
        engine.rollback(
            checkpoint
            .checkpoint_id
        )
    )

    assert (
        result.success
        is False
    )

    assert (
        result.data[
            "failure_type"
        ]
        == "stale_rollback"
    )

    assert (
        file_path.read_text(
            encoding="utf-8"
        )
        == "revision-2"
    )


# =============================================================
# Unknown Checkpoint
# =============================================================


def test_rollback_unknown_checkpoint_fails(
    tmp_path: Path,
):

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    engine = (
        RollbackEngine(
            workspace=tmp_path,
            checkpoint_manager=(
                manager
            ),
        )
    )

    result = (
        engine.rollback(
            "cp-does-not-exist"
        )
    )

    assert (
        result.success
        is False
    )

    assert (
        result.data[
            "failure_type"
        ]
        == "checkpoint_not_found"
    )


# =============================================================
# Unsealed Checkpoint
# =============================================================


def test_unsealed_checkpoint_cannot_rollback(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.txt"
    )

    file_path.write_text(
        "before",
        encoding="utf-8",
    )

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    checkpoint = (
        manager.capture(
            path="demo.txt",
            edit_revision=1,
        )
    )

    engine = (
        RollbackEngine(
            workspace=tmp_path,
            checkpoint_manager=(
                manager
            ),
        )
    )

    result = (
        engine.rollback(
            checkpoint
            .checkpoint_id
        )
    )

    assert (
        result.success
        is False
    )

    assert (
        result.data[
            "failure_type"
        ]
        == "checkpoint_unsealed"
    )


# =============================================================
# Double Rollback
# =============================================================


def test_checkpoint_cannot_rollback_twice(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.txt"
    )

    file_path.write_text(
        "before",
        encoding="utf-8",
    )

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    checkpoint = (
        manager.capture(
            path="demo.txt",
            edit_revision=1,
        )
    )

    file_path.write_text(
        "after",
        encoding="utf-8",
    )

    manager.seal(
        checkpoint.checkpoint_id
    )

    engine = (
        RollbackEngine(
            workspace=tmp_path,
            checkpoint_manager=(
                manager
            ),
        )
    )

    first = (
        engine.rollback(
            checkpoint
            .checkpoint_id
        )
    )

    second = (
        engine.rollback(
            checkpoint
            .checkpoint_id
        )
    )

    assert (
        first.success
        is True
    )

    assert (
        second.success
        is False
    )

    assert (
        second.data[
            "failure_type"
        ]
        == (
            "checkpoint_already_rolled_back"
        )
    )


# =============================================================
# Exact Content Preservation
# =============================================================


def test_rollback_restores_exact_content(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    original = (
        "def hello():\n"
        "    return '你好'\n"
        "\n"
    )

    file_path.write_text(
        original,
        encoding="utf-8",
    )

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    checkpoint = (
        manager.capture(
            path="demo.py",
            edit_revision=1,
        )
    )

    file_path.write_text(
        (
            "def hello():\n"
            "    return 'changed'\n"
        ),
        encoding="utf-8",
    )

    manager.seal(
        checkpoint.checkpoint_id
    )

    engine = (
        RollbackEngine(
            workspace=tmp_path,
            checkpoint_manager=(
                manager
            ),
        )
    )

    result = (
        engine.rollback(
            checkpoint
            .checkpoint_id
        )
    )

    assert (
        result.success
        is True
    )

    assert (
        file_path.read_text(
            encoding="utf-8"
        )
        == original
    )