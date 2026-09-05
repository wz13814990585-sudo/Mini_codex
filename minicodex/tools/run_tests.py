import re
import subprocess
import sys
from pathlib import Path

from .base import BaseTool
from .results import ToolResult


MAX_FAILURE_DETAIL_LINES = 40
MAX_FAILED_TEST_NAMES = 20


VALID_PURPOSES = {
    "acceptance",
    "regression",
}


class RunTestsTool(
    BaseTool
):

    name = "run_tests"

    description = (
        "Run Python tests using pytest and return structured "
        "validation evidence. Use purpose='acceptance' for "
        "specific tests that demonstrate the user's requested "
        "behavior. Use purpose='regression' for existing or "
        "full-suite regression validation."
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Test path such as "
                    "'minicodex/tests/test_example.py'. "
                    "Use '.' for the full regression suite."
                ),
            },
            "purpose": {
                "type": "string",
                "enum": [
                    "acceptance",
                    "regression",
                ],
                "description": (
                    "Validation purpose. "
                    "'acceptance' demonstrates that the "
                    "specific behavior requested by the user "
                    "works. 'regression' checks that existing "
                    "behavior remains correct."
                ),
            },
        },
        "required": [],
    }

    def __init__(
        self,
        workspace: str = ".",
        timeout: int = 60,
    ):
        self.workspace = Path(
            workspace
        ).resolve()

        self.timeout = timeout

    def execute(
        self,
        path: str = ".",
        purpose: str = "regression",
    ) -> ToolResult:

        normalized_path = str(
            path
        ).strip()

        normalized_purpose = (
            str(
                purpose
            )
            .strip()
            .lower()
        )

        # =====================================================
        # Purpose Validation
        # =====================================================

        if (
            normalized_purpose
            not in VALID_PURPOSES
        ):

            raise ValueError(
                (
                    "purpose must be either "
                    "'acceptance' or 'regression'."
                )
            )

        # =====================================================
        # Acceptance Must Be Targeted
        # =====================================================

        if (
            normalized_purpose
            == "acceptance"
            and normalized_path
            in {
                "",
                ".",
                "./",
            }
        ):

            raise ValueError(
                (
                    "Acceptance validation must target "
                    "a specific test path. "
                    "The full suite cannot by itself serve "
                    "as acceptance evidence."
                )
            )

        if not normalized_path:

            normalized_path = "."

        command = [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:debugging",
            normalized_path,
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
                    "path": normalized_path,
                    "purpose": (
                        normalized_purpose
                    ),
                    "timeout": self.timeout,
                    "timed_out": True,
                },
                error=(
                    "pytest execution timed out"
                ),
            )

        parsed = (
            parse_pytest_output(
                exit_code=(
                    process.returncode
                ),
                stdout=(
                    process.stdout
                ),
                stderr=(
                    process.stderr
                ),
            )
        )

        llm_content = (
            build_pytest_llm_content(
                parsed
            )
        )

        summary = (
            build_pytest_summary(
                parsed
            )
        )

        return ToolResult(
            success=True,
            summary=summary,
            data={
                "path": normalized_path,
                "purpose": (
                    normalized_purpose
                ),
                **parsed,
            },
            llm_content=(
                llm_content
            ),
        )


def parse_pytest_output(
    exit_code: int,
    stdout: str,
    stderr: str,
) -> dict:

    passed = (
        _extract_count(
            stdout,
            "passed",
        )
    )

    failed = (
        _extract_count(
            stdout,
            "failed",
        )
    )

    errors = (
        _extract_count(
            stdout,
            "error",
        )
        + _extract_count(
            stdout,
            "errors",
        )
    )

    skipped = (
        _extract_count(
            stdout,
            "skipped",
        )
    )

    xfailed = (
        _extract_count(
            stdout,
            "xfailed",
        )
    )

    xpassed = (
        _extract_count(
            stdout,
            "xpassed",
        )
    )

    failed_tests = (
        _extract_failed_test_names(
            stdout
        )
    )

    failure_details = (
        _failure_detail_lines(
            stdout.splitlines(),
            MAX_FAILURE_DETAIL_LINES,
        )
    )

    stderr_lines = [
        line
        for line
        in stderr.splitlines()
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
        "failure_details": (
            failure_details
        ),
        "stderr": (
            stderr_lines[:20]
        ),
        "tests_passed": (
            exit_code == 0
        ),
        "timed_out": False,
    }


def build_pytest_summary(
    parsed: dict,
) -> str:

    parts = []

    if parsed[
        "passed"
    ]:

        parts.append(
            f"{parsed['passed']} passed"
        )

    if parsed[
        "failed"
    ]:

        parts.append(
            f"{parsed['failed']} failed"
        )

    if parsed[
        "errors"
    ]:

        parts.append(
            f"{parsed['errors']} errors"
        )

    if parsed[
        "skipped"
    ]:

        parts.append(
            f"{parsed['skipped']} skipped"
        )

    if not parts:

        parts.append(
            (
                "pytest exited with code "
                f"{parsed['exit_code']}"
            )
        )

    return (
        ", ".join(
            parts
        )
        + "."
    )


def build_pytest_llm_content(
    parsed: dict,
) -> str:

    sections = [
        (
            "Exit code: "
            f"{parsed['exit_code']}"
        )
    ]

    if parsed[
        "failed_tests"
    ]:

        sections.append(
            (
                "FAILED TESTS:\n"
                + "\n".join(
                    parsed[
                        "failed_tests"
                    ]
                )
            )
        )

    if parsed[
        "failure_details"
    ]:

        sections.append(
            (
                "DETAILS:\n"
                + "\n".join(
                    parsed[
                        "failure_details"
                    ]
                )
            )
        )

    if parsed[
        "stderr"
    ]:

        sections.append(
            (
                "STDERR:\n"
                + "\n".join(
                    parsed[
                        "stderr"
                    ]
                )
            )
        )

    return "\n".join(
        sections
    )


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

    for line in (
        stdout.splitlines()
    ):

        if not (
            line.startswith(
                "FAILED "
            )
        ):

            continue

        failed_names.append(
            line.strip()
        )

        if (
            len(
                failed_names
            )
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
            "FAILURES"
            in line
            or line.startswith(
                "FAILED "
            )
            or line.startswith(
                "E "
            )
            or line.startswith(
                "E\t"
            )
        ):

            capturing = True

        if capturing:

            if re.fullmatch(
                r"\.+",
                line.strip(),
            ):

                continue

            detail.append(
                line
            )

            if (
                len(
                    detail
                )
                >= max_fail_lines
            ):

                break

    return detail