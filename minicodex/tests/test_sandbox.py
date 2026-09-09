import os
import sys

from ..agent.safety import (
    SandboxLimits,
    SandboxRunner,
)


# =============================================================
# Basic Execution
# =============================================================


def test_sandbox_executes_process(
    tmp_path,
):

    sandbox = (
        SandboxRunner(
            workspace=(
                tmp_path
            )
        )
    )

    result = (
        sandbox.run_argv(
            [
                sys.executable,
                "-c",
                (
                    "print('hello "
                    "sandbox')"
                ),
            ]
        )
    )

    assert (
        result.started
        is True
    )

    assert (
        result.exit_code
        == 0
    )

    assert (
        result.command_succeeded
        is True
    )

    assert (
        "hello sandbox"
        in result.stdout
    )


# =============================================================
# Fixed Workspace
# =============================================================


def test_sandbox_uses_workspace_cwd(
    tmp_path,
):

    sandbox = (
        SandboxRunner(
            workspace=(
                tmp_path
            )
        )
    )

    result = (
        sandbox.run_argv(
            [
                sys.executable,
                "-c",
                (
                    "import os; "
                    "print(os.getcwd())"
                ),
            ]
        )
    )

    assert (
        result.exit_code
        == 0
    )

    assert (
        str(
            tmp_path.resolve()
        )
        in result.stdout
    )


# =============================================================
# Environment Isolation
# =============================================================


def test_sandbox_does_not_inherit_arbitrary_secret(
    tmp_path,
    monkeypatch,
):

    monkeypatch.setenv(
        "MINICODEX_SECRET_TEST",
        "super-secret",
    )

    sandbox = (
        SandboxRunner(
            workspace=(
                tmp_path
            )
        )
    )

    result = (
        sandbox.run_argv(
            [
                sys.executable,
                "-c",
                (
                    "import os; "
                    "print("
                    "os.environ.get("
                    "'MINICODEX_SECRET_TEST', "
                    "'MISSING'"
                    "))"
                ),
            ]
        )
    )

    assert (
        result.exit_code
        == 0
    )

    assert (
        "MISSING"
        in result.stdout
    )

    assert (
        "super-secret"
        not in result.stdout
    )


# =============================================================
# Sandbox HOME
# =============================================================


def test_sandbox_replaces_home_directory(
    tmp_path,
):

    sandbox = (
        SandboxRunner(
            workspace=(
                tmp_path
            )
        )
    )

    result = (
        sandbox.run_argv(
            [
                sys.executable,
                "-c",
                (
                    "import os; "
                    "print("
                    "os.environ['HOME']"
                    ")"
                ),
            ]
        )
    )

    assert (
        result.exit_code
        == 0
    )

    expected = (
        tmp_path
        / ".minicodex"
        / "sandbox"
        / "home"
    )

    assert (
        str(
            expected
        )
        in result.stdout
    )


# =============================================================
# Timeout
# =============================================================


def test_sandbox_timeout(
    tmp_path,
):

    sandbox = (
        SandboxRunner(
            workspace=(
                tmp_path
            ),
            limits=(
                SandboxLimits(
                    timeout_seconds=0.2,
                    max_cpu_seconds=5,
                )
            ),
        )
    )

    result = (
        sandbox.run_argv(
            [
                sys.executable,
                "-c",
                (
                    "import time; "
                    "time.sleep(5)"
                ),
            ]
        )
    )

    assert (
        result.started
        is True
    )

    assert (
        result.timed_out
        is True
    )

    assert (
        result.command_succeeded
        is False
    )


# =============================================================
# Output Bound
# =============================================================


def test_sandbox_output_is_bounded(
    tmp_path,
):

    sandbox = (
        SandboxRunner(
            workspace=(
                tmp_path
            ),
            limits=(
                SandboxLimits(
                    max_output_bytes=64,
                    max_file_bytes=(
                        1024
                        * 1024
                    ),
                )
            ),
        )
    )

    result = (
        sandbox.run_argv(
            [
                sys.executable,
                "-c",
                (
                    "print('x' * 10000)"
                ),
            ]
        )
    )

    assert (
        result.started
        is True
    )

    assert (
        result.output_limited
        is True
    )

    assert (
        "[Sandbox output truncated]"
        in result.stdout
    )

    # Captured payload itself remains bounded.
    assert (
        len(
            result.stdout
        )
        < 200
    )


# =============================================================
# Metadata Is Explicit About Isolation Strength
# =============================================================


def test_sandbox_metadata_does_not_overclaim_isolation(
    tmp_path,
):

    sandbox = (
        SandboxRunner(
            workspace=(
                tmp_path
            )
        )
    )

    result = (
        sandbox.run_argv(
            [
                sys.executable,
                "-c",
                "print('ok')",
            ]
        )
    )

    metadata = (
        result
        .sandbox_metadata()
    )

    assert (
        metadata[
            "mode"
        ]
        == "process"
    )

    assert (
        metadata[
            "environment_sanitized"
        ]
        is True
    )

    assert (
        metadata[
            "filesystem_isolated"
        ]
        is False
    )

    assert (
        metadata[
            "network_isolated"
        ]
        is False
    )