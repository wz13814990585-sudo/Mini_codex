from pathlib import Path

from ..agent.sandbox import (
    SandboxLimits,
    SandboxRunner,
)

from .base import BaseTool
from .results import ToolResult


class RunCommandTool(
    BaseTool
):

    name = (
        "run_command"
    )

    description = (
        "Run a shell command inside the current project "
        "workspace through the MiniCodex process sandbox and "
        "return stdout, stderr, exit code, and sandbox metadata. "
        "Do not use this to run pytest; call run_tests instead."
    )

    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "Shell command to execute, "
                    "for example "
                    "'python calculator.py'."
                ),
            },
        },
        "required": [
            "command",
        ],
    }

    def __init__(
        self,
        workspace: str = ".",
        timeout: int = 30,
        sandbox: (
            SandboxRunner
            | None
        ) = None,
    ):

        self.workspace = (
            Path(
                workspace
            )
            .resolve()
        )

        self.timeout = max(
            1,
            int(
                timeout
            ),
        )

        self.sandbox = (
            sandbox
            or SandboxRunner(
                workspace=(
                    self.workspace
                ),
                limits=(
                    SandboxLimits(
                        timeout_seconds=(
                            self.timeout
                        )
                    )
                ),
            )
        )

    # =========================================================
    # Execute
    # =========================================================

    def execute(
        self,
        command: str,
    ) -> ToolResult:

        sandbox_result = (
            self.sandbox
            .run_shell(
                command,
                timeout_seconds=(
                    self.timeout
                ),
            )
        )

        # =====================================================
        # Sandbox Could Not Start
        # =====================================================

        if not (
            sandbox_result.started
        ):

            return ToolResult(
                success=False,
                summary=(
                    "Command could not be started "
                    "inside the process sandbox."
                ),
                data={
                    "command": (
                        command
                    ),
                    "exit_code": None,
                    "command_succeeded": (
                        False
                    ),
                    "stdout": "",
                    "stderr": "",
                    "timed_out": (
                        False
                    ),
                    "sandbox": (
                        sandbox_result
                        .sandbox_metadata()
                    ),
                    "failure_type": (
                        sandbox_result
                        .failure_type
                        or "sandbox_start"
                    ),
                },
                error=(
                    sandbox_result.error
                    or (
                        "Sandbox process "
                        "could not start."
                    )
                ),
            )

        # =====================================================
        # Timeout
        # =====================================================

        if (
            sandbox_result
            .timed_out
        ):

            return ToolResult(
                success=False,
                summary=(
                    "Command timed out after "
                    f"{self.timeout} seconds "
                    "inside the sandbox."
                ),
                data={
                    "command": (
                        command
                    ),
                    "exit_code": (
                        sandbox_result
                        .exit_code
                    ),
                    "command_succeeded": (
                        False
                    ),
                    "stdout": (
                        sandbox_result
                        .stdout
                    ),
                    "stderr": (
                        sandbox_result
                        .stderr
                    ),
                    "timed_out": True,
                    "output_truncated": (
                        sandbox_result
                        .output_limited
                    ),
                    "timeout": (
                        self.timeout
                    ),
                    "sandbox": (
                        sandbox_result
                        .sandbox_metadata()
                    ),
                    "failure_type": (
                        "sandbox_timeout"
                    ),
                },
                error=(
                    "Command execution "
                    "timed out."
                ),
            )

        stdout = (
            sandbox_result
            .stdout
            or ""
        )

        stderr = (
            sandbox_result
            .stderr
            or ""
        )

        command_succeeded = (
            sandbox_result
            .command_succeeded
        )

        exit_code = (
            sandbox_result
            .exit_code
        )

        # =====================================================
        # Summary
        # =====================================================

        if (
            command_succeeded
        ):

            summary = (
                "Command completed "
                "successfully inside the "
                "sandbox with exit code "
                f"{exit_code}."
            )

        else:

            summary = (
                "Command completed inside "
                "the sandbox with exit code "
                f"{exit_code}."
            )

        if (
            sandbox_result
            .output_limited
        ):

            summary += (
                " Captured output was "
                "truncated by the sandbox."
            )

        # =====================================================
        # LLM Observation
        # =====================================================

        llm_parts = [
            (
                "Exit code: "
                f"{exit_code}"
            )
        ]

        if (
            sandbox_result
            .output_limited
        ):

            llm_parts.append(
                (
                    "Sandbox note: captured "
                    "output was truncated."
                )
            )

        if (
            stdout.strip()
        ):

            llm_parts.append(
                (
                    "STDOUT:\n"
                    + stdout
                )
            )

        if (
            stderr.strip()
        ):

            llm_parts.append(
                (
                    "STDERR:\n"
                    + stderr
                )
            )

        llm_content = "\n".join(
            llm_parts
        )

        return ToolResult(
            success=True,
            summary=(
                summary
            ),
            data={
                "command": (
                    command
                ),
                "exit_code": (
                    exit_code
                ),
                "command_succeeded": (
                    command_succeeded
                ),
                "stdout": (
                    stdout
                ),
                "stderr": (
                    stderr
                ),
                "timed_out": False,
                "output_truncated": (
                    sandbox_result
                    .output_limited
                ),
                "sandbox": (
                    sandbox_result
                    .sandbox_metadata()
                ),
            },
            llm_content=(
                llm_content
            ),
        )