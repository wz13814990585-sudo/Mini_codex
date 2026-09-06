"""Controlled Python dependency installation."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import re
import sys

from ..agent.sandbox import (
    SandboxLimits,
    SandboxRunner,
)

from .base import BaseTool
from .results import ToolResult


PACKAGE_SPEC_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*"
    r"(?:\[[A-Za-z0-9._,-]+\])?"
    r"(?:(?:==|>=|<=|~=|!=|>|<)"
    r"[A-Za-z0-9][A-Za-z0-9.*+!_-]*)?$"
)

IMPORT_NAME_PATTERN = re.compile(
    r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$"
)


class InstallPythonPackageTool(BaseTool):
    """Install one package without exposing a shell command surface."""

    name = "install_python_package"

    description = (
        "Install a missing Python package into the same Python "
        "environment that runs MiniCodex, then verify its import. "
        "Use only after a concrete ModuleNotFoundError or failed "
        "import. Provide the distribution name as package and the "
        "Python module name as import_name (for example package="
        "'Pillow', import_name='PIL'). URLs, local paths, shell "
        "options, and multiple packages are rejected."
    )

    parameters = {
        "type": "object",
        "properties": {
            "package": {
                "type": "string",
                "description": (
                    "PyPI distribution name with an optional single "
                    "version constraint, for example 'requests>=2.31'."
                ),
            },
            "import_name": {
                "type": "string",
                "description": (
                    "Module path used by Python import, for example "
                    "'requests', 'PIL', or 'google.cloud.storage'."
                ),
            },
        },
        "required": [
            "package",
            "import_name",
        ],
    }

    def __init__(
        self,
        workspace: str | Path = ".",
        timeout: int = 120,
        sandbox: SandboxRunner | None = None,
        python_executable: str | None = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.timeout = max(1, int(timeout))
        self.python_executable = str(
            python_executable
            or sys.executable
        )
        self.sandbox = sandbox or SandboxRunner(
            workspace=self.workspace,
            limits=SandboxLimits(
                timeout_seconds=self.timeout,
            ),
        )

    def execute(
        self,
        package: str,
        import_name: str,
    ) -> ToolResult:
        package = str(package).strip()
        import_name = str(import_name).strip()

        self._validate_package(package)
        self._validate_import_name(import_name)

        if self._module_available(import_name):
            return ToolResult(
                success=True,
                summary=(
                    f"Python module '{import_name}' is already "
                    "available; installation was not needed."
                ),
                data={
                    "package": package,
                    "import_name": import_name,
                    "interpreter": self.python_executable,
                    "installed": False,
                    "already_available": True,
                    "import_verified": True,
                    "exit_code": 0,
                },
            )

        install_result = self.sandbox.run_argv(
            [
                self.python_executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                package,
            ],
            timeout_seconds=self.timeout,
        )

        if not install_result.started or install_result.timed_out:
            return self._failure_result(
                package=package,
                import_name=import_name,
                result=install_result,
                failure_type=(
                    "install_timeout"
                    if install_result.timed_out
                    else "install_start"
                ),
            )

        if install_result.exit_code != 0:
            return self._failure_result(
                package=package,
                import_name=import_name,
                result=install_result,
                failure_type="install_failed",
            )

        importlib.invalidate_caches()
        import_verified = self._module_available(
            import_name
        )

        if not import_verified:
            return ToolResult(
                success=False,
                summary=(
                    f"Installed '{package}', but Python module "
                    f"'{import_name}' could not be found. Check the "
                    "distribution-to-import name mapping."
                ),
                data=self._result_data(
                    package,
                    import_name,
                    install_result,
                    installed=True,
                    import_verified=False,
                    failure_type="import_verification_failed",
                ),
                error=(
                    "Package installation completed but import "
                    "verification failed."
                ),
            )

        return ToolResult(
            success=True,
            summary=(
                f"Installed '{package}' and verified import "
                f"'{import_name}' using {self.python_executable}."
            ),
            data=self._result_data(
                package,
                import_name,
                install_result,
                installed=True,
                import_verified=True,
            ),
        )

    @staticmethod
    def _validate_package(package: str) -> None:
        if not PACKAGE_SPEC_PATTERN.fullmatch(package):
            raise ValueError(
                "package must be one PyPI distribution name with "
                "an optional version constraint; URLs, paths, "
                "options, and shell syntax are not allowed."
            )

    @staticmethod
    def _validate_import_name(import_name: str) -> None:
        if not IMPORT_NAME_PATTERN.fullmatch(import_name):
            raise ValueError(
                "import_name must be a valid dotted Python module name."
            )

    @staticmethod
    def _module_available(import_name: str) -> bool:
        try:
            return importlib.util.find_spec(
                import_name
            ) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def _failure_result(
        self,
        *,
        package: str,
        import_name: str,
        result,
        failure_type: str,
    ) -> ToolResult:
        return ToolResult(
            success=False,
            summary=(
                f"Could not install Python package '{package}'."
            ),
            data=self._result_data(
                package,
                import_name,
                result,
                installed=False,
                import_verified=False,
                failure_type=failure_type,
            ),
            error=(
                result.error
                or result.stderr.strip()
                or "pip installation failed."
            ),
        )

    def _result_data(
        self,
        package: str,
        import_name: str,
        result,
        *,
        installed: bool,
        import_verified: bool,
        failure_type: str | None = None,
    ) -> dict:
        return {
            "package": package,
            "import_name": import_name,
            "interpreter": self.python_executable,
            "installed": installed,
            "already_available": False,
            "import_verified": import_verified,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
            "output_truncated": result.output_limited,
            "sandbox": result.sandbox_metadata(),
            "failure_type": failure_type,
        }
