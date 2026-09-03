import re
import subprocess
import sys
from pathlib import Path

from minicodex.tools.base import BaseTool


MAX_FAILURE_DETAIL_LINES = 40


class RunTestsTool(BaseTool):

    name = "run_tests"

    description = (
        "Run the project's Python tests using pytest and return "
        "the exit code, a short summary, and failing details. "
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
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:debugging",
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

        return compact_pytest_output(
            result.returncode,
            result.stdout,
            result.stderr,
        )


def compact_pytest_output(
    exit_code: int,
    stdout: str,
    stderr: str,
    max_fail_lines: int = MAX_FAILURE_DETAIL_LINES,
) -> str:
    stdout_lines = stdout.splitlines()
    parts = [f"Exit code: {exit_code}"]

    summary_lines = [
        line
        for line in stdout_lines
        if re.search(
            r"\d+\s+(passed|failed|error|errors)",
            line,
            re.IGNORECASE,
        )
    ]
    failed_names = [
        line
        for line in stdout_lines
        if line.startswith("FAILED ")
    ]

    if summary_lines:
        parts.append("SUMMARY:\n" + "\n".join(summary_lines[-3:]))

    if failed_names:
        parts.append(
            "FAILED:\n" + "\n".join(failed_names[:20])
        )

    detail = _failure_detail_lines(
        stdout_lines,
        max_fail_lines,
    )
    if detail:
        parts.append("DETAILS:\n" + "\n".join(detail))
    elif not summary_lines:
        parts.append(
            "STDOUT:\n" + "\n".join(stdout_lines[:max_fail_lines])
        )

    stderr_lines = [
        line for line in stderr.splitlines() if line.strip()
    ]
    if stderr_lines:
        parts.append(
            "STDERR:\n" + "\n".join(stderr_lines[:20])
        )

    return "\n".join(parts)


def _failure_detail_lines(
    stdout_lines: list[str],
    max_fail_lines: int,
) -> list[str]:
    detail = []
    capturing = False

    for line in stdout_lines:
        if (
            "FAILURES" in line
            or line.startswith("FAILED ")
            or line.startswith("E ")
            or line.startswith("E\t")
        ):
            capturing = True

        if capturing:
            if re.fullmatch(r"\.+", line.strip()):
                continue
            detail.append(line)
            if len(detail) >= max_fail_lines:
                break

    return detail
