"""Controlled Python dependency installation."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import re
import sys

from ...agent.safety import (
    SandboxLimits,
    SandboxRunner,
)
from ...agent.context.project_execution_environment import ProjectExecutionEnvironment

from ..base import BaseTool
from ..results import ToolResult


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
    capabilities = frozenset({"dependency.install"})
    """Install one package without exposing a shell command surface."""

    name = "install_python_package"

    description = (
        "将缺失的 Python 包安装到所选目标项目环境中，"
        "并用同一环境验证 import。"
        "仅在出现明确的 ModuleNotFoundError 或导入失败后使用。"
        "package 填发行版名称，import_name 填 Python 模块名"
        "（例如 package='Pillow'，import_name='PIL'）。"
        "URL、本地路径、shell 选项以及一次安装多个包都会被拒绝。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "package": {
                "type": "string",
                "description": (
                    "PyPI 发行版名称，可带单个版本约束，"
                    "例如 'requests>=2.31'。"
                ),
            },
            "import_name": {
                "type": "string",
                "description": (
                    "Python import 使用的模块路径，例如 "
                    "'requests'、'PIL' 或 'google.cloud.storage'。"
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
            or ProjectExecutionEnvironment.discover(self.workspace).python_executable
        )
        self.environment = ProjectExecutionEnvironment.discover(self.workspace)
        if python_executable:
            from dataclasses import replace
            self.environment = replace(self.environment, python_executable=self.python_executable,
                                       python_command_prefix=(self.python_executable,), command_available=True)
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
                    f"Python 模块 '{import_name}' 已可用；"
                    "无需安装。"
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

        install_argv = self.environment.pip_install_argv(package)
        if not self.environment.command_available or install_argv is None:
            return ToolResult(
                success=False,
                summary="在不改动项目依赖状态的前提下，目标项目依赖安装不可用。",
                data={"package": package, "import_name": import_name, "installed": False,
                      "import_verified": False, "failure_type": "environment_unavailable",
                      "environment": self.environment.summary(), "argv": list(install_argv or ())},
                error="所选 uv/poetry 环境需要明确的依赖策略；未修改任何锁文件。",
            )
        install_result = self.sandbox.run_argv(list(install_argv), timeout_seconds=self.timeout)

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
                    f"已安装 '{package}'，但找不到 Python 模块 "
                    f"'{import_name}'。请检查发行版名与 import 名的对应关系。"
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
                    "包安装已完成，但 import 验证失败。"
                ),
            )

        return ToolResult(
            success=True,
            summary=(
                f"已安装 '{package}'，并用 {self.python_executable} "
                f"验证了 import '{import_name}'。"
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
                "package 必须是单个 PyPI 发行版名称，"
                "可带可选版本约束；不允许 URL、路径、"
                "选项或 shell 语法。"
            )

    @staticmethod
    def _validate_import_name(import_name: str) -> None:
        if not IMPORT_NAME_PATTERN.fullmatch(import_name):
            raise ValueError(
                "import_name 必须是合法的点分 Python 模块名。"
            )

    def _module_available(self, import_name: str) -> bool:
        """Probe the target project interpreter, never the MiniCodex host."""
        if not Path(self.python_executable).is_file():
            # A symbolic interpreter is only used by deterministic unit-test
            # adapters; real discovered project environments are always
            # executed through module_probe_argv below.
            try:
                return importlib.util.find_spec(import_name) is not None
            except (ImportError, ModuleNotFoundError, ValueError):
                return False
        if not self.environment.command_available:
            return False
        result = self.sandbox.run_argv(
            list(self.environment.module_probe_argv(import_name)), timeout_seconds=self.timeout
        )
        return bool(result.started and not result.timed_out and result.exit_code == 0)

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
                f"无法安装 Python 包 '{package}'。"
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
                or "pip 安装失败。"
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
            "environment": self.environment.summary(),
            "argv": list(getattr(result, "argv", ()) or ()),
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
