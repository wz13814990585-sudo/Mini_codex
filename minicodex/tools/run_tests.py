import subprocess
from pathlib import Path

from tools.base import BaseTool


class RunTestsTool(BaseTool):

    name = "run_tests"

    description = (
        "Run the project's Python tests using pytest and return "
        "the exit code, stdout, and stderr. "
        "Use this after modifying code when tests are available."
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Optional test path, such as 'tests/' "
                    "or 'tests/test_calculator.py'. "
                    "Use '.' to run the full test suite."
                )
            }
        },
        "required": []
    }

    def __init__(
        self,
        workspace: str = ".",
        timeout: int = 60
    ):
        self.workspace = Path(workspace).resolve()
        self.timeout = timeout

    def execute(self, path: str = ".") -> str:

        command = [
            "python",
            "-m",
            "pytest",
            path,
            "-q"
        ]

        try:
            result = subprocess.run(
                command,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

        except subprocess.TimeoutExpired:
            return (
                f"Tests timed out after "
                f"{self.timeout} seconds."
            )

        return (
            f"Exit code: {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )