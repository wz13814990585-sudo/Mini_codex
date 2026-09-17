"""Deterministic target-project runtime discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True)
class ProjectExecutionEnvironment:
    workspace: Path
    python_executable: str
    package_manager: str = ""

    @classmethod
    def discover(cls, workspace):
        root = Path(workspace).resolve()
        candidates = (root / ".venv" / "bin" / "python", root / "venv" / "bin" / "python",
                      root / ".venv" / "Scripts" / "python.exe", root / "venv" / "Scripts" / "python.exe")
        python = next((str(path) for path in candidates if path.is_file()), sys.executable)
        manager = "pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists() else "npm" if (root / "package.json").exists() else ""
        return cls(root, python, manager)

    def summary(self):
        return f"Python: {self.python_executable}; package manager: {self.package_manager or 'none'}"
