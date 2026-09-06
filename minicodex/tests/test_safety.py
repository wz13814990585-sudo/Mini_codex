import subprocess

from ..agent.git_awareness import (
    GitAwareness,
    GitRepositoryInspector,
)
from ..agent.safety import (
    SafetyLevel,
    SafetyPolicy,
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
        / "tracked.py"
    )

    path.write_text(
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

    return path


def build_policy(
    tmp_path,
):

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

    policy = (
        SafetyPolicy(
            workspace=tmp_path,
            git_awareness=(
                awareness
            ),
        )
    )

    return (
        policy,
        awareness,
    )


# =============================================================
# SAFE Tool
# =============================================================


def test_read_tool_is_safe(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "read_file",
            {
                "path": (
                    "demo.py"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is True
    )

    assert (
        decision.level
        == SafetyLevel.SAFE
    )


# =============================================================
# SAFE Edit
# =============================================================


def test_normal_workspace_edit_is_safe(
    tmp_path,
):

    make_repo(
        tmp_path
    )

    (
        policy,
        _,
    ) = (
        build_policy(
            tmp_path
        )
    )

    decision = (
        policy.assess(
            "write_file",
            {
                "path": (
                    "new_file.py"
                ),
                "content": (
                    "value = 1\n"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is True
    )

    assert (
        decision.level
        == SafetyLevel.SAFE
    )


# =============================================================
# Workspace Escape
# =============================================================


def test_workspace_escape_is_blocked(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "write_file",
            {
                "path": (
                    "../outside.py"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is False
    )

    assert (
        decision.level
        == SafetyLevel.BLOCKED
    )

    assert (
        decision.rule
        == "workspace_escape"
    )


# =============================================================
# Git Metadata
# =============================================================


def test_git_metadata_edit_is_blocked(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "write_file",
            {
                "path": (
                    ".git/config"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is False
    )

    assert (
        decision.rule
        == (
            "git_metadata_protection"
        )
    )


# =============================================================
# Pre-existing User Work
# =============================================================


def test_preexisting_dirty_file_is_caution(
    tmp_path,
):

    tracked = (
        make_repo(
            tmp_path
        )
    )

    tracked.write_text(
        "user_change = True\n",
        encoding="utf-8",
    )

    (
        policy,
        _,
    ) = (
        build_policy(
            tmp_path
        )
    )

    decision = (
        policy.assess(
            "replace_lines",
            {
                "path": (
                    "tracked.py"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is True
    )

    assert (
        decision.level
        == SafetyLevel.CAUTION
    )

    assert (
        decision.rule
        == "preexisting_user_change"
    )


# =============================================================
# rm
# =============================================================


def test_rm_command_is_blocked(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "rm -rf build"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is False
    )

    assert (
        decision.rule
        == "destructive_rm"
    )


def test_absolute_rm_command_is_blocked(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "/bin/rm -rf build"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is False
    )

    assert (
        decision.rule
        == "destructive_rm"
    )


# =============================================================
# Git Mutation
# =============================================================


def test_git_reset_is_blocked(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "git reset --hard HEAD"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is False
    )

    assert (
        decision.rule
        == "git_mutation"
    )


def test_absolute_git_reset_is_blocked(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "/usr/bin/git reset "
                    "--hard HEAD"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is False
    )

    assert (
        decision.rule
        == "git_mutation"
    )


def test_git_clean_is_blocked(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "git clean -fd"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is False
    )


def test_git_branch_delete_is_blocked(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "git branch -D feature"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is False
    )

    assert (
        decision.rule
        == "git_reference_mutation"
    )


# =============================================================
# Shell Redirection
# =============================================================


def test_shell_file_redirection_is_blocked(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "echo hello > demo.txt"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is False
    )

    assert (
        decision.rule
        == (
            "checkpoint_bypass_redirection"
        )
    )


def test_stderr_file_redirection_is_blocked(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "python demo.py "
                    "2>error.log"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is False
    )

    assert (
        decision.rule
        == (
            "checkpoint_bypass_redirection"
        )
    )


def test_dev_null_redirection_is_allowed(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "python demo.py "
                    "2>/dev/null"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is True
    )


def test_stderr_to_stdout_fd_redirect_is_allowed(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "python demo.py "
                    "2>&1"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is True
    )


def test_stdout_to_stderr_fd_redirect_is_allowed(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "python demo.py "
                    "1>&2"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is True
    )


def test_dev_null_and_fd_redirect_are_allowed(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "python demo.py "
                    ">/dev/null 2>&1"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is True
    )


# =============================================================
# Read-only Git
# =============================================================


def test_git_status_command_is_safe(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "git status --short"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is True
    )

    assert (
        decision.level
        == SafetyLevel.SAFE
    )


def test_absolute_git_status_is_safe(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "/usr/bin/git "
                    "status --short"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is True
    )


# =============================================================
# Network
# =============================================================


def test_network_command_is_caution(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "curl "
                    "https://example.com"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is True
    )

    assert (
        decision.level
        == SafetyLevel.CAUTION
    )

    assert (
        decision.rule
        == "network_access"
    )


def test_absolute_curl_is_caution(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "/usr/bin/curl "
                    "https://example.com"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is True
    )

    assert (
        decision.level
        == SafetyLevel.CAUTION
    )

    assert (
        decision.rule
        == "network_access"
    )


# =============================================================
# Dependency Install
# =============================================================


def test_package_install_is_caution(
    tmp_path,
):

    policy = (
        SafetyPolicy(
            workspace=tmp_path
        )
    )

    decision = (
        policy.assess(
            "run_command",
            {
                "command": (
                    "python -m pip "
                    "install requests"
                ),
            },
        )
    )

    assert (
        decision.allowed
        is True
    )

    assert (
        decision.level
        == SafetyLevel.CAUTION
    )