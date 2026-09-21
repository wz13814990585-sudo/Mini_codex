import subprocess

from ..agent.runtime import (
    GitAwareness,
    GitRepositoryInspector,
)


def run_git(
    repo,
    *args,
):

    return subprocess.run(
        [
            "git",
            "-C",
            str(
                repo
            ),
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )


def make_repo(
    tmp_path,
):

    run_git(
        tmp_path,
        "init",
    )

    run_git(
        tmp_path,
        "config",
        "user.email",
        "test@example.com",
    )

    run_git(
        tmp_path,
        "config",
        "user.name",
        "MiniCodex Test",
    )

    tracked = (
        tmp_path
        / "tracked.py"
    )

    tracked.write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    run_git(
        tmp_path,
        "add",
        "tracked.py",
    )

    run_git(
        tmp_path,
        "commit",
        "-m",
        "initial",
    )

    return tracked


# =============================================================
# Clean Repository
# =============================================================


def test_clean_git_repository(
    tmp_path,
):

    make_repo(
        tmp_path
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    state = (
        inspector.snapshot()
    )

    assert (
        state.git_available
        is True
    )

    assert (
        state.is_repo
        is True
    )

    assert (
        state.head_sha
        is not None
    )

    assert (
        state.dirty
        is False
    )

    assert (
        state.changed_files
        == ()
    )


# =============================================================
# Modified + Untracked
# =============================================================


def test_modified_and_untracked_files(
    tmp_path,
):

    tracked = (
        make_repo(
            tmp_path
        )
    )

    tracked.write_text(
        "value = 2\n",
        encoding="utf-8",
    )

    (
        tmp_path
        / "new.py"
    ).write_text(
        "new = True\n",
        encoding="utf-8",
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    state = (
        inspector.snapshot()
    )

    assert (
        state.dirty
        is True
    )

    assert (
        "tracked.py"
        in state.modified_files
    )

    assert (
        "new.py"
        in state.untracked_files
    )


# =============================================================
# Staged
# =============================================================


def test_staged_file_is_detected(
    tmp_path,
):

    tracked = (
        make_repo(
            tmp_path
        )
    )

    tracked.write_text(
        "value = 2\n",
        encoding="utf-8",
    )

    run_git(
        tmp_path,
        "add",
        "tracked.py",
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    state = (
        inspector.snapshot()
    )

    assert (
        "tracked.py"
        in state.staged_files
    )


# =============================================================
# Deleted
# =============================================================


def test_deleted_file_is_detected(
    tmp_path,
):

    tracked = (
        make_repo(
            tmp_path
        )
    )

    tracked.unlink()

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    state = (
        inspector.snapshot()
    )

    assert (
        "tracked.py"
        in state.deleted_files
    )


# =============================================================
# Tracked Diff
# =============================================================


def test_git_diff_reads_workspace_changes(
    tmp_path,
):

    tracked = (
        make_repo(
            tmp_path
        )
    )

    tracked.write_text(
        "value = 99\n",
        encoding="utf-8",
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    diff = (
        inspector.diff(
            path="tracked.py"
        )
    )

    assert (
        diff.success
        is True
    )

    assert (
        "+value = 99"
        in diff.text
    )


# =============================================================
# Staged Diff
# =============================================================


def test_staged_git_diff(
    tmp_path,
):

    tracked = (
        make_repo(
            tmp_path
        )
    )

    tracked.write_text(
        "value = 50\n",
        encoding="utf-8",
    )

    run_git(
        tmp_path,
        "add",
        "tracked.py",
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    diff = (
        inspector.diff(
            path="tracked.py",
            staged=True,
        )
    )

    assert (
        diff.success
        is True
    )

    assert (
        "+value = 50"
        in diff.text
    )


# =============================================================
# Untracked Diff
# =============================================================


def test_untracked_file_has_synthetic_git_diff(
    tmp_path,
):

    make_repo(
        tmp_path
    )

    new_file = (
        tmp_path
        / "feature.py"
    )

    new_file.write_text(
        (
            "def feature():\n"
            "    return True\n"
        ),
        encoding="utf-8",
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    diff = (
        inspector.diff(
            path="feature.py"
        )
    )

    assert (
        diff.success
        is True
    )

    assert (
        "new file mode"
        in diff.text
    )

    assert (
        "+def feature():"
        in diff.text
    )

    assert (
        "+    return True"
        in diff.text
    )


def test_full_git_diff_includes_untracked_files(
    tmp_path,
):

    make_repo(
        tmp_path
    )

    (
        tmp_path
        / "new.py"
    ).write_text(
        "new_value = 123\n",
        encoding="utf-8",
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    diff = (
        inspector.diff()
    )

    assert (
        diff.success
        is True
    )

    assert (
        "new.py"
        in diff.text
    )

    assert (
        "+new_value = 123"
        in diff.text
    )


# =============================================================
# Baseline Ownership
# =============================================================


def test_task_baseline_distinguishes_user_and_agent_changes(
    tmp_path,
):

    tracked = (
        make_repo(
            tmp_path
        )
    )

    # User-owned pre-existing work.
    tracked.write_text(
        "value = 2\n",
        encoding="utf-8",
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    awareness = (
        GitAwareness(
            inspector
        )
    )

    awareness.reset_task()

    (
        tmp_path
        / "agent_change.py"
    ).write_text(
        "agent = True\n",
        encoding="utf-8",
    )

    awareness.record_agent_edit(
        "agent_change.py"
    )

    task = (
        awareness.refresh()
    )

    assert (
        "tracked.py"
        in (
            task
            .pre_existing_changed_files
        )
    )

    assert (
        "agent_change.py"
        in (
            task
            .agent_touched_files
        )
    )

    assert (
        "agent_change.py"
        in (
            task
            .agent_current_changed_files
        )
    )

    assert (
        "agent_change.py"
        in (
            task
            .agent_introduced_files
        )
    )

    assert (
        "tracked.py"
        not in (
            task
            .agent_introduced_files
        )
    )


# =============================================================
# Touch Existing User Work
# =============================================================


def test_agent_touching_preexisting_change_is_detected(
    tmp_path,
):

    tracked = (
        make_repo(
            tmp_path
        )
    )

    tracked.write_text(
        "user work\n",
        encoding="utf-8",
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    awareness = (
        GitAwareness(
            inspector
        )
    )

    awareness.reset_task()

    awareness.record_agent_edit(
        "tracked.py"
    )

    task = (
        awareness.refresh()
    )

    assert (
        "tracked.py"
        in (
            task
            .agent_touched_preexisting_files
        )
    )


# =============================================================
# Rollback / Restore Semantics
# =============================================================


def test_restored_file_is_not_current_agent_change(
    tmp_path,
):

    tracked = (
        make_repo(
            tmp_path
        )
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    awareness = (
        GitAwareness(
            inspector
        )
    )

    awareness.reset_task()

    # Agent modifies.
    tracked.write_text(
        "value = 999\n",
        encoding="utf-8",
    )

    awareness.record_agent_edit(
        "tracked.py"
    )

    changed = (
        awareness.refresh()
    )

    assert (
        "tracked.py"
        in changed
        .agent_current_changed_files
    )

    # Simulate deterministic rollback.
    tracked.write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    restored = (
        awareness.refresh()
    )

    # Historical fact remains.
    assert (
        "tracked.py"
        in restored
        .agent_touched_files
    )

    # But current ownership disappears.
    assert (
        "tracked.py"
        not in restored
        .agent_current_changed_files
    )

    assert (
        "tracked.py"
        not in restored
        .agent_introduced_files
    )

    assert (
        restored.current.dirty
        is False
    )


# =============================================================
# Refresh Is Source Of Truth
# =============================================================


def test_refresh_updates_current_git_state(
    tmp_path,
):

    tracked = (
        make_repo(
            tmp_path
        )
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    awareness = (
        GitAwareness(
            inspector
        )
    )

    awareness.reset_task()

    assert (
        awareness.current.dirty
        is False
    )

    tracked.write_text(
        "value = 777\n",
        encoding="utf-8",
    )

    awareness.record_agent_edit(
        "tracked.py"
    )

    # Before refresh, current is intentionally a cached snapshot.
    assert (
        awareness.current.dirty
        is False
    )

    task = (
        awareness.refresh()
    )

    assert (
        task.current.dirty
        is True
    )

    assert (
        "tracked.py"
        in task.current.changed_files
    )