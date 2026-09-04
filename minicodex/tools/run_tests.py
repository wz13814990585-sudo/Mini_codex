import re
import subprocess
import sys
from pathlib import Path

from .base import BaseTool
from .results import ToolResult


MAX_FAILURE_DETAIL_LINES = 40
MAX_FAILED_TEST_NAMES = 20


class RunTestsTool(BaseTool):

    name = "run_tests"

    description = (
        "Run the project's Python tests using pytest and return "
        "structured test results, a short summary, and failing details. "
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
                ),
            }
        },
        "required": [],
    }

    def __init__(
        self,
        workspace: str = ".",
        timeout: int = 60,
    ):
        self.workspace = Path(workspace).resolve()
        self.timeout = timeout

    def execute(
        self,
        path: str = ".",
    ) -> ToolResult:

        command = [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:debugging",
            path,
            "-q",
        ]

        try:
            process = subprocess.run(
                command,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                summary=(
                    f"Tests timed out after "
                    f"{self.timeout} seconds."
                ),
                data={
                    "path": path,
                    "timeout": self.timeout,
                    "timed_out": True,
                },
                error="pytest execution timed out",
            )

        parsed = parse_pytest_output(
            exit_code=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
        )

        llm_content = build_pytest_llm_content(
            parsed
        )

        summary = build_pytest_summary(
            parsed
        )

        return ToolResult(
            success=True,
            summary=summary,
            data={
                "path": path,
                **parsed,
            },
            llm_content=llm_content,
        )


def parse_pytest_output(
    exit_code: int,
    stdout: str,
    stderr: str,
) -> dict:
    passed = _extract_count(
        stdout,
        "passed",
    )

    failed = _extract_count(
        stdout,
        "failed",
    )

    errors = _extract_count(
        stdout,
        "error",
    ) + _extract_count(
        stdout,
        "errors",
    )

    skipped = _extract_count(
        stdout,
        "skipped",
    )

    xfailed = _extract_count(
        stdout,
        "xfailed",
    )

    xpassed = _extract_count(
        stdout,
        "xpassed",
    )

    failed_tests = _extract_failed_test_names(
        stdout
    )

    failure_details = _failure_detail_lines(
        stdout.splitlines(),
        MAX_FAILURE_DETAIL_LINES,
    )

    stderr_lines = [
        line
        for line in stderr.splitlines()
        if line.strip()
    ]

    return {
        "exit_code": exit_code,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "xfailed": xfailed,
        "xpassed": xpassed,
        "failed_tests": failed_tests,
        "failure_details": failure_details,
        "stderr": stderr_lines[:20],
        "tests_passed": exit_code == 0,
        "timed_out": False,
    }


def build_pytest_summary(
    parsed: dict,
) -> str:

    parts = []

    if parsed["passed"]:
        parts.append(
            f"{parsed['passed']} passed"
        )

    if parsed["failed"]:
        parts.append(
            f"{parsed['failed']} failed"
        )

    if parsed["errors"]:
        parts.append(
            f"{parsed['errors']} errors"
        )

    if parsed["skipped"]:
        parts.append(
            f"{parsed['skipped']} skipped"
        )

    if not parts:
        parts.append(
            f"pytest exited with code "
            f"{parsed['exit_code']}"
        )

    return ", ".join(parts) + "."


def build_pytest_llm_content(
    parsed: dict,
) -> str:

    sections = [
        f"Exit code: {parsed['exit_code']}"
    ]

    if parsed["failed_tests"]:
        sections.append(
            "FAILED TESTS:\n"
            + "\n".join(
                parsed["failed_tests"]
            )
        )

    if parsed["failure_details"]:
        sections.append(
            "DETAILS:\n"
            + "\n".join(
                parsed["failure_details"]
            )
        )

    if parsed["stderr"]:
        sections.append(
            "STDERR:\n"
            + "\n".join(
                parsed["stderr"]
            )
        )

    return "\n".join(sections)


def _extract_count(
    text: str,
    label: str,
) -> int:

    pattern = (
        rf"(\d+)\s+"
        rf"{re.escape(label)}\b"
    )

    matches = re.findall(
        pattern,
        text,
        re.IGNORECASE,
    )

    if not matches:
        return 0

    return int(
        matches[-1]
    )


def _extract_failed_test_names(
    stdout: str,
) -> list[str]:

    failed_names = []

    for line in stdout.splitlines():

        if not line.startswith("FAILED "):
            continue

        failed_names.append(
            line.strip()
        )

        if (
            len(failed_names)
            >= MAX_FAILED_TEST_NAMES
        ):
            break

    return failed_names


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

            if re.fullmatch(
                r"\.+",
                line.strip(),
            ):
                continue

            detail.append(line)

            if (
                len(detail)
                >= max_fail_lines
            ):
                break

    return detail