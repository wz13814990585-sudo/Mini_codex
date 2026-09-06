from pathlib import Path

import pytest

from ..agent.checkpoint import (
    CheckpointManager,
)
from ..tools.edit_verifier import (
    EditVerifier,
)


# =============================================================
# Capture Existing File
# =============================================================


def test_capture_existing_file(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    content = (
        "def run():\n"
        "    return 1\n"
    )

    file_path.write_text(
        content,
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

    assert (
        checkpoint.checkpoint_id
        == "cp-000001"
    )

    assert (
        checkpoint.edit_revision
        == 1
    )

    assert (
        checkpoint.snapshot.path
        == "demo.py"
    )

    assert (
        checkpoint.snapshot.existed
        is True
    )

    assert (
        checkpoint.snapshot.content
        == content
    )

    assert (
        checkpoint.snapshot.sha256
        == (
            EditVerifier
            .content_hash(
                content
            )
        )
    )


# =============================================================
# Capture Missing File
# =============================================================


def test_capture_missing_file(
    tmp_path: Path,
):

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    checkpoint = (
        manager.capture(
            path="new_file.py",
            edit_revision=1,
        )
    )

    assert (
        checkpoint.snapshot.existed
        is False
    )

    assert (
        checkpoint.snapshot.content
        is None
    )

    assert (
        checkpoint.snapshot.sha256
        is None
    )


# =============================================================
# Multiple Checkpoints
# =============================================================


def test_checkpoint_ids_increment(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.txt"
    )

    file_path.write_text(
        "one",
        encoding="utf-8",
    )

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    first = (
        manager.capture(
            path="demo.txt",
            edit_revision=1,
        )
    )

    file_path.write_text(
        "two",
        encoding="utf-8",
    )

    second = (
        manager.capture(
            path="demo.txt",
            edit_revision=2,
        )
    )

    assert (
        first.checkpoint_id
        == "cp-000001"
    )

    assert (
        second.checkpoint_id
        == "cp-000002"
    )

    assert (
        first.snapshot.content
        == "one"
    )

    assert (
        second.snapshot.content
        == "two"
    )


# =============================================================
# Latest
# =============================================================


def test_latest_checkpoint(
    tmp_path: Path,
):

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    manager.capture(
        path="a.txt",
        edit_revision=1,
    )

    second = (
        manager.capture(
            path="b.txt",
            edit_revision=2,
        )
    )

    assert (
        manager.latest()
        == second
    )


# =============================================================
# Get By ID
# =============================================================


def test_get_checkpoint_by_id(
    tmp_path: Path,
):

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

    assert (
        manager.get(
            checkpoint.checkpoint_id
        )
        == checkpoint
    )

    assert (
        manager.get(
            "cp-does-not-exist"
        )
        is None
    )


# =============================================================
# Latest For Path
# =============================================================


def test_latest_checkpoint_for_path(
    tmp_path: Path,
):

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    manager.capture(
        path="a.txt",
        edit_revision=1,
    )

    expected = (
        manager.capture(
            path="b.txt",
            edit_revision=2,
        )
    )

    manager.capture(
        path="a.txt",
        edit_revision=3,
    )

    assert (
        manager.latest_for_path(
            "b.txt"
        )
        == expected
    )


# =============================================================
# Latest For Revision
# =============================================================


def test_latest_checkpoint_for_revision(
    tmp_path: Path,
):

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    manager.capture(
        path="a.txt",
        edit_revision=1,
    )

    expected = (
        manager.capture(
            path="b.txt",
            edit_revision=2,
        )
    )

    assert (
        manager.latest_for_revision(
            2
        )
        == expected
    )


# =============================================================
# Bounded History
# =============================================================


def test_checkpoint_history_is_bounded(
    tmp_path: Path,
):

    manager = (
        CheckpointManager(
            workspace=tmp_path,
            max_checkpoints=2,
        )
    )

    first = (
        manager.capture(
            path="a.txt",
            edit_revision=1,
        )
    )

    second = (
        manager.capture(
            path="b.txt",
            edit_revision=2,
        )
    )

    third = (
        manager.capture(
            path="c.txt",
            edit_revision=3,
        )
    )

    history = (
        manager.all_checkpoints()
    )

    assert (
        len(history)
        == 2
    )

    assert (
        first
        not in history
    )

    assert (
        history
        == (
            second,
            third,
        )
    )


# =============================================================
# Reset
# =============================================================


def test_checkpoint_reset(
    tmp_path: Path,
):

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    manager.capture(
        path="demo.txt",
        edit_revision=1,
    )

    manager.reset()

    assert (
        manager.latest()
        is None
    )

    assert (
        manager.all_checkpoints()
        == ()
    )

    # Counter also restarts for a new task.
    checkpoint = (
        manager.capture(
            path="demo.txt",
            edit_revision=1,
        )
    )

    assert (
        checkpoint.checkpoint_id
        == "cp-000001"
    )


# =============================================================
# Invalid Revision
# =============================================================


def test_checkpoint_rejects_invalid_revision(
    tmp_path: Path,
):

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    with pytest.raises(
        ValueError,
        match="edit_revision",
    ):

        manager.capture(
            path="demo.txt",
            edit_revision=0,
        )


# =============================================================
# Empty Path
# =============================================================


def test_checkpoint_rejects_empty_path(
    tmp_path: Path,
):

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    with pytest.raises(
        ValueError,
        match="path",
    ):

        manager.capture(
            path="   ",
            edit_revision=1,
        )

def test_discard_checkpoint(
    tmp_path: Path,
):

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    first = (
        manager.capture(
            path="a.txt",
            edit_revision=1,
        )
    )

    second = (
        manager.capture(
            path="b.txt",
            edit_revision=2,
        )
    )

    removed = (
        manager.discard(
            second.checkpoint_id
        )
    )

    assert (
        removed
        is True
    )

    assert (
        manager.latest()
        == first
    )

    assert (
        manager.get(
            second.checkpoint_id
        )
        is None
    )


def test_discard_unknown_checkpoint_returns_false(
    tmp_path: Path,
):

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    assert (
        manager.discard(
            "cp-does-not-exist"
        )
        is False
    )

    