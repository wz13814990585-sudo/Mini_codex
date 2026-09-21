from types import SimpleNamespace

import pytest

from ..tools.execution import (
    InstallPythonPackageTool,
)


class FakeSandbox:
    def __init__(
        self,
        *,
        exit_code=0,
        started=True,
        timed_out=False,
    ):
        self.exit_code = exit_code
        self.started = started
        self.timed_out = timed_out
        self.calls = []

    def run_argv(
        self,
        command,
        *,
        timeout_seconds,
    ):
        self.calls.append(
            (list(command), timeout_seconds)
        )
        return SimpleNamespace(
            started=self.started,
            timed_out=self.timed_out,
            exit_code=self.exit_code,
            stdout="installed\n",
            stderr=(
                ""
                if self.exit_code == 0
                else "package not found"
            ),
            output_limited=False,
            error=None,
            sandbox_metadata=lambda: {
                "mode": "process"
            },
        )


def test_existing_module_does_not_run_pip(
    tmp_path,
):
    sandbox = FakeSandbox()
    tool = InstallPythonPackageTool(
        workspace=tmp_path,
        sandbox=sandbox,
        python_executable="/python",
    )

    result = tool.execute(
        package="pytest",
        import_name="pytest",
    )

    assert result.success is True
    assert result.data["already_available"] is True
    assert result.data["installed"] is False
    assert sandbox.calls == []


def test_missing_module_is_installed_with_direct_argv(
    tmp_path,
    monkeypatch,
):
    sandbox = FakeSandbox()
    tool = InstallPythonPackageTool(
        workspace=tmp_path,
        sandbox=sandbox,
        python_executable="/project/.venv/bin/python",
    )
    availability = iter([False, True])
    monkeypatch.setattr(
        tool,
        "_module_available",
        lambda name: next(availability),
    )

    result = tool.execute(
        package="requests>=2.31",
        import_name="requests",
    )

    assert result.success is True
    assert result.data["installed"] is True
    assert result.data["import_verified"] is True
    assert sandbox.calls[0][0] == [
        "/project/.venv/bin/python",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "requests>=2.31",
    ]


def test_failed_pip_install_returns_tool_failure(
    tmp_path,
    monkeypatch,
):
    sandbox = FakeSandbox(exit_code=1)
    tool = InstallPythonPackageTool(
        workspace=tmp_path,
        sandbox=sandbox,
    )
    monkeypatch.setattr(
        tool,
        "_module_available",
        lambda name: False,
    )

    result = tool.execute(
        package="missing-package",
        import_name="missing_package",
    )

    assert result.success is False
    assert result.data["failure_type"] == "install_failed"
    assert "package not found" in result.error


@pytest.mark.parametrize(
    "package",
    [
        "requests flask",
        "--index-url=evil.example/pkg",
        "https://example.test/pkg.whl",
        "requests; touch owned",
        "../local-package",
    ],
)
def test_unsafe_package_spec_is_rejected(
    tmp_path,
    package,
):
    tool = InstallPythonPackageTool(
        workspace=tmp_path,
        sandbox=FakeSandbox(),
    )

    with pytest.raises(ValueError, match="package"):
        tool.execute(
            package=package,
            import_name="requests",
        )


def test_invalid_import_name_is_rejected(
    tmp_path,
):
    tool = InstallPythonPackageTool(
        workspace=tmp_path,
        sandbox=FakeSandbox(),
    )

    with pytest.raises(ValueError, match="import_name"):
        tool.execute(
            package="requests",
            import_name="requests;boom",
        )
