import subprocess

from ..agent.git_awareness import (
    GitAwareness,
    GitRepositoryInspector,
)
from ..tools.git_diff import (
    GitDiffTool,
)
from ..tools.git_status import (
    GitStatusTool,
)


def run_git(
    repo,
    *args,
):

    subprocess.run(
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

    path = (
        tmp_path
        / "demo.py"
    )

    path.write_text(
        "value = 1\n",
        encoding="utf-8",
    )

    run_git(
        tmp_path,
        "add",
        "demo.py",
    )

    run_git(
        tmp_path,
        "commit",
        "-m",
        "initial",
    )

    return path


# =============================================================
# Git Status Tool
# =============================================================


def test_git_status_tool(
    tmp_path,
):

    path = (
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

    path.write_text(
        "value = 2\n",
        encoding="utf-8",
    )

    awareness.record_agent_edit(
        "demo.py"
    )

    tool = (
        GitStatusTool(
            awareness
        )
    )

    result = (
        tool.execute()
    )

    assert (
        result.success
        is True
    )

    assert (
        result.data[
            "current"
        ][
            "dirty"
        ]
        is True
    )

    assert (
        "demo.py"
        in result.data[
            "agent_touched_files"
        ]
    )

    assert (
        "demo.py"
        in result.data[
            "agent_current_changed_files"
        ]
    )


# =============================================================
# Git Diff Tool
# =============================================================


def test_git_diff_tool(
    tmp_path,
):

    path = (
        make_repo(
            tmp_path
        )
    )

    path.write_text(
        "value = 3\n",
        encoding="utf-8",
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    tool = (
        GitDiffTool(
            inspector
        )
    )

    result = (
        tool.execute(
            path="demo.py"
        )
    )

    assert (
        result.success
        is True
    )

    assert (
        "+value = 3"
        in result.llm_content
    )


# =============================================================
# Untracked Git Diff Tool
# =============================================================


def test_git_diff_tool_shows_untracked_file(
    tmp_path,
):

    make_repo(
        tmp_path
    )

    (
        tmp_path
        / "feature.py"
    ).write_text(
        (
            "def new_feature():\n"
            "    return 42\n"
        ),
        encoding="utf-8",
    )

    inspector = (
        GitRepositoryInspector(
            tmp_path
        )
    )

    tool = (
        GitDiffTool(
            inspector
        )
    )

    result = (
        tool.execute(
            path="feature.py"
        )
    )

    assert (
        result.success
        is True
    )

    assert (
        "new file mode"
        in result.llm_content
    )

    assert (
        "+def new_feature():"
        in result.llm_content
    )


# =============================================================
# Workspace Guard
# =============================================================


def test_git_diff_rejects_outside_workspace(
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

    tool = (
        GitDiffTool(
            inspector
        )
    )

    result = (
        tool.execute(
            path="../outside.py"
        )
    )

    assert (
        result.success
        is False
    )