import subprocess
from pathlib import Path

from .base import BaseTool
from .results import ToolResult


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
                ),
            }
        },
        "required": ["command"],
    }

    def __init__(
        self,
        workspace: str = ".",
        timeout: int = 30,
    ):
        self.workspace = Path(workspace).resolve()
        self.timeout = timeout

    def execute(
        self,
        command: str,
    ) -> ToolResult:

        try:
            process = subprocess.run(
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
                timeout=self.timeout,
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                summary=(
                    f"Command timed out after "
                    f"{self.timeout} seconds."
                ),
                data={
                    "command": command,
                    "timed_out": True,
                    "timeout": self.timeout,
                },
                error="Command execution timed out.",
            )

        stdout = process.stdout or ""
        stderr = process.stderr or ""

        command_succeeded = (
            process.returncode == 0
        )

        if command_succeeded:
            summary = (
                f"Command completed successfully "
                f"with exit code {process.returncode}."
            )
        else:
            summary = (
                f"Command completed with "
                f"exit code {process.returncode}."
            )

        llm_parts = [
            f"Exit code: {process.returncode}"
        ]

        if stdout.strip():
            llm_parts.append(
                "STDOUT:\n"
                + stdout
            )

        if stderr.strip():
            llm_parts.append(
                "STDERR:\n"
                + stderr
            )

        llm_content = "\n".join(
            llm_parts
        )

        return ToolResult(
            success=True,
            summary=summary,
            data={
                "command": command,
                "exit_code": process.returncode,
                "command_succeeded": command_succeeded,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": False,
            },
            llm_content=llm_content,
        )