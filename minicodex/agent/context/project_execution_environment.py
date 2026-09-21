"""Deterministic target-project runtime discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import sys


@dataclass(frozen=True)
class ProjectExecutionEnvironment:
    workspace: Path
    python_executable: str
    package_manager: str = ""
    python_command_prefix: tuple[str, ...] = ()
    test_command: tuple[str, ...] = ()
    command_available: bool = True

    @classmethod
    def discover(cls, workspace):
        root = Path(workspace).resolve()
        candidates = (root / ".venv" / "bin" / "python", root / "venv" / "bin" / "python",
                      root / ".venv" / "Scripts" / "python.exe", root / "venv" / "Scripts" / "python.exe")
        python = next((str(path) for path in candidates if path.is_file()), sys.executable)
        manager = "pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists() else "npm" if (root / "package.json").exists() else ""
        if (root / "uv.lock").exists():
            prefix, test = ("uv", "run", "python"), ("uv", "run", "pytest")
            command_available = shutil.which("uv") is not None
        elif (root / "poetry.lock").exists():
            prefix, test = ("poetry", "run", "python"), ("poetry", "run", "pytest")
            command_available = shutil.which("poetry") is not None
        else:
            prefix, test = (python,), (python, "-m", "pytest")
            command_available = Path(python).is_file() or shutil.which(python) is not None
        return cls(root, python, manager, prefix, test, command_available)

    def python_argv(self, *arguments: str) -> tuple[str, ...]:
        return (*self.python_command_prefix, *map(str, arguments))

    def pytest_argv(self, *arguments: str) -> tuple[str, ...]:
        return (*self.test_command, *map(str, arguments))

    def module_probe_argv(self, module: str) -> tuple[str, ...]:
        return self.python_argv("-c", f"import {module}")

    def pip_install_argv(self, package: str) -> tuple[str, ...] | None:
        # `uv run`/`poetry run` should not be used to silently mutate a
        # lockfile or declaration. DependencyResolver owns that policy.
        if self.python_command_prefix[:1] in {("uv",), ("poetry",)}:
            return None
        return self.python_argv("-m", "pip", "install", "--disable-pip-version-check", package)

    def summary(self):
        mode = "available" if self.command_available else "missing executable"
        return f"Python: {' '.join(self.python_command_prefix)} ({mode}); package manager: {self.package_manager or 'none'}"
