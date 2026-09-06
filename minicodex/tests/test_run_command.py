import sys

from ..agent.sandbox import (
    SandboxLimits,
    SandboxRunner,
)
from ..tools.run_command import (
    RunCommandTool,
)


def test_run_command_success(
    tmp_path,
):

    tool = (
        RunCommandTool(
            workspace=str(
                tmp_path
            )
        )
    )

    result = (
        tool.execute(
            (
                f"\"{sys.executable}\" "
                "-c \"print('hello')\""
            )
        )
    )

    assert (
        result.success
        is True
    )

    assert (
        result.data[
            "exit_code"
        ]
        == 0
    )

    assert (
        result.data[
            "command_succeeded"
        ]
        is True
    )

    assert (
        "hello"
        in result.data[
            "stdout"
        ]
    )

    assert (
        result.data[
            "sandbox"
        ][
            "mode"
        ]
        == "process"
    )


def test_run_command_nonzero_exit_is_not_tool_failure(
    tmp_path,
):

    tool = (
        RunCommandTool(
            workspace=str(
                tmp_path
            )
        )
    )

    result = (
        tool.execute(
            (
                f"\"{sys.executable}\" "
                "-c "
                "\"raise SystemExit(2)\""
            )
        )
    )

    assert (
        result.success
        is True
    )

    assert (
        result.data[
            "exit_code"
        ]
        == 2
    )

    assert (
        result.data[
            "command_succeeded"
        ]
        is False
    )


def test_run_command_preserves_acceptance_purpose(
    tmp_path,
):
    tool = RunCommandTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(
        f'"{sys.executable}" -c "print(\'PASS\')"',
        purpose="acceptance",
    )

    assert result.success is True
    assert result.data["purpose"] == "acceptance"


def test_run_command_rejects_unknown_purpose(
    tmp_path,
):
    import pytest

    tool = RunCommandTool(
        workspace=str(tmp_path)
    )

    with pytest.raises(ValueError, match="purpose"):
        tool.execute(
            "true",
            purpose="other",
        )


def test_run_command_timeout_is_tool_failure(
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

    tool = (
        RunCommandTool(
            workspace=str(
                tmp_path
            ),
            timeout=1,
            sandbox=(
                sandbox
            ),
        )
    )

    # Tool timeout overrides shared sandbox default.
    tool.timeout = (
        0.2
    )

    result = (
        tool.execute(
            (
                f"\"{sys.executable}\" "
                "-c "
                "\"import time; "
                "time.sleep(5)\""
            )
        )
    )

    assert (
        result.success
        is False
    )

    assert (
        result.data[
            "timed_out"
        ]
        is True
    )

    assert (
        result.data[
            "failure_type"
        ]
        == "sandbox_timeout"
    )


def test_run_command_secret_env_is_not_inherited(
    tmp_path,
    monkeypatch,
):

    monkeypatch.setenv(
        "MINICODEX_PRIVATE_KEY",
        "do-not-leak",
    )

    tool = (
        RunCommandTool(
            workspace=(
                tmp_path
            )
        )
    )

    result = (
        tool.execute(
            (
                f"\"{sys.executable}\" "
                "-c "
                "\"import os; "
                "print("
                "os.environ.get("
                "'MINICODEX_PRIVATE_KEY', "
                "'missing'"
                "))\""
            )
        )
    )

    assert (
        result.success
        is True
    )

    assert (
        "missing"
        in result.data[
            "stdout"
        ]
    )

    assert (
        "do-not-leak"
        not in result.data[
            "stdout"
        ]
    )
