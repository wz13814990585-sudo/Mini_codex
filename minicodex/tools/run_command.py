import subprocess
from pathlib import Path

from minicodex.tools.base import BaseTool


class RunCommandTool(BaseTool):

    name = "run_command"

    description = (
        "Run a shell command inside the current project workspace "
        "and return stdout, stderr, and the exit code. "
        "Do not use this to run pytest; call run_tests instead."
    )

    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "Shell command to execute, "
                    "for example 'python calculator.py'."
                )
            }
        },
        "required": ["command"]
    }

    def __init__(
        self,
        workspace: str = ".",
        timeout: int = 30
    ):
        self.workspace = Path(workspace).resolve()
        self.timeout = timeout

    def execute(self, command: str) -> str:
        try:
            result = subprocess.run(
                [
                    "/bin/bash",
                    "-o",
                    "pipefail",
                    "-c",
                    command,
                ],
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

        except subprocess.TimeoutExpired:
            return (
                f"Command timed out after "
                f"{self.timeout} seconds."
            )

        output = (
            f"Exit code: {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

        return output
