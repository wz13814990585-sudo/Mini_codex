import re
import sys
from pathlib import Path

from ...agent.safety import (
    SandboxLimits,
    SandboxRunner,
)

from ..base import BaseTool
from ..results import ToolResult
from ...agent.validation import TestTargetResolver


MAX_FAILURE_DETAIL_LINES = 40

MAX_FAILED_TEST_NAMES = 20


VALID_PURPOSES = {
    "acceptance",
    "regression",
}


class RunTestsTool(
    BaseTool
):

    name = (
        "run_tests"
    )

    description = (
        "Run Python tests using pytest inside the MiniCodex "
        "process sandbox and return structured validation "
        "evidence. Use purpose='acceptance' for specific tests "
        "that demonstrate the user's requested behavior. Use "
        "purpose='regression' for existing or full-suite "
        "regression validation."
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
                    "'acceptance' demonstrates "
                    "the specific requested behavior. "
                    "'regression' checks existing "
                    "behavior."
                ),
            },
        },
        "required": [],
    }

    def __init__(
        self,
        workspace: str = ".",
        timeout: int = 60,
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
        path: str = ".",
        purpose: str = "regression",
    ) -> ToolResult:

        normalized_path = (
            str(
                path
            )
            .strip()
        )

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
                    "'acceptance' or "
                    "'regression'."
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
                    "Acceptance validation "
                    "must target a specific "
                    "test path. The full suite "
                    "cannot by itself serve as "
                    "acceptance evidence."
                )
            )

        if (
            normalized_purpose == "acceptance"
            and not TestTargetResolver.is_test_path(normalized_path)
        ):
            raise ValueError(
                "Acceptance validation must target an actual test file or "
                "pytest node id; a source module is not acceptance evidence."
            )

        if not (
            normalized_path
        ):

            normalized_path = (
                "."
            )

        # =====================================================
        # Workspace Guard
        # =====================================================

        normalized_path = (
            self._normalize_test_path(
                normalized_path
            )
        )

        # =====================================================
        # pytest argv
        # =====================================================

        command = [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:debugging",
            normalized_path,
            "-q",
        ]

        sandbox_result = (
            self.sandbox
            .run_argv(
                command,
                timeout_seconds=(
                    self.timeout
                ),
            )
        )

        # =====================================================
        # Sandbox Start Failure
        # =====================================================

        if not (
            sandbox_result.started
        ):

            return ToolResult(
                success=False,
                summary=(
                    "Tests could not be started "
                    "inside the process sandbox."
                ),
                data={
                    "path": (
                        normalized_path
                    ),
                    "purpose": (
                        normalized_purpose
                    ),
                    "timed_out": False,
                    "sandbox": (
                        sandbox_result
                        .sandbox_metadata()
                    ),
                    "failure_type": (
                        sandbox_result
                        .failure_type
                        or "sandbox_start"
                    ),
                    "outcome": "inconclusive",
                    "failed_count": None,
                    "validation_summary": "Tests could not be started.",
                },
                error=(
                    sandbox_result.error
                    or (
                        "Sandbox pytest "
                        "process could not start."
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
                    "Tests timed out after "
                    f"{self.timeout} seconds "
                    "inside the sandbox."
                ),
                data={
                    "path": (
                        normalized_path
                    ),
                    "purpose": (
                        normalized_purpose
                    ),
                    "timeout": (
                        self.timeout
                    ),
                    "timed_out": True,
                    "output_truncated": (
                        sandbox_result
                        .output_limited
                    ),
                    "sandbox": (
                        sandbox_result
                        .sandbox_metadata()
                    ),
                    "failure_type": (
                        "sandbox_timeout"
                    ),
                    "outcome": "inconclusive",
                    "failed_count": None,
                    "validation_summary": "Tests timed out.",
                },
                error=(
                    "pytest execution "
                    "timed out"
                ),
            )

        # =====================================================
        # Parse pytest result
        # =====================================================

        parsed = (
            parse_pytest_output(
                exit_code=(
                    sandbox_result
                    .exit_code
                    if (
                        sandbox_result
                        .exit_code
                        is not None
                    )
                    else -1
                ),
                stdout=(
                    sandbox_result
                    .stdout
                ),
                stderr=(
                    sandbox_result
                    .stderr
                ),
                workspace=self.workspace,
            )
        )

        parsed[
            "output_truncated"
        ] = (
            sandbox_result
            .output_limited
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

        if (
            sandbox_result
            .output_limited
        ):

            summary += (
                " Captured pytest output "
                "was truncated by the sandbox."
            )

        return ToolResult(
            success=True,
            summary=(
                summary
            ),
            data={
                "path": (
                    normalized_path
                ),
                "purpose": (
                    normalized_purpose
                ),
                **parsed,
                "outcome": (
                    "passed" if parsed["tests_passed"] else "failed"
                ),
                "failed_count": parsed["failed"] + parsed["errors"],
                "validation_summary": summary,
                "sandbox": (
                    sandbox_result
                    .sandbox_metadata()
                ),
            },
            llm_content=(
                llm_content
            ),
        )

    # =========================================================
    # Test Path Guard
    # =========================================================

    def _normalize_test_path(
        self,
        path: str,
    ) -> str:

        if (
            path
            in {
                ".",
                "./",
            }
        ):

            return "."

        candidate = (
            (
                self.workspace
                / path
            )
            .resolve()
        )

        try:

            relative = (
                candidate
                .relative_to(
                    self.workspace
                )
            )

        except ValueError:

            raise ValueError(
                (
                    "Test path must remain "
                    "inside the workspace."
                )
            )

        return (
            relative
            .as_posix()
        )


# =============================================================
# Parse pytest
# =============================================================


def parse_pytest_output(
    exit_code: int,
    stdout: str,
    stderr: str,
    workspace: str | Path | None = None,
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

    failure_paths = extract_failure_paths(
        stdout=stdout,
        stderr=stderr,
        workspace=workspace,
    )
    combined_output = f"{stdout}\n{stderr}"
    missing_dependency = re.search(
        r"(?:ModuleNotFoundError:\s*No module named|ImportError:\s*No module named)\s*['\"]([^'\"]+)",
        combined_output,
    )

    return {
        "exit_code": (
            exit_code
        ),
        "passed": (
            passed
        ),
        "failed": (
            failed
        ),
        "errors": (
            errors
        ),
        "skipped": (
            skipped
        ),
        "xfailed": (
            xfailed
        ),
        "xpassed": (
            xpassed
        ),
        "failed_tests": (
            failed_tests
        ),
        "failure_details": (
            failure_details
        ),
        "failure_paths": failure_paths,
        "failure_type": "missing_dependency" if missing_dependency else (
            "regression_failed" if exit_code else None
        ),
        "missing_module": missing_dependency.group(1) if missing_dependency else None,
        "stderr": (
            stderr_lines[
                :20
            ]
        ),
        "tests_passed": (
            exit_code
            == 0
        ),
        "timed_out": False,
    }


def extract_failure_paths(
    *,
    stdout: str,
    stderr: str,
    workspace: str | Path | None = None,
) -> list[str]:
    """Conservatively extract repo-local paths from pytest diagnostics."""

    candidates: list[str] = []
    for line in stdout.splitlines():
        if line.startswith("FAILED ") or line.startswith("ERROR "):
            token = line.split(maxsplit=1)[1].split("::", 1)[0].strip()
            candidates.append(token)

    traceback_pattern = re.compile(
        r"(?<![\w.-])((?:[A-Za-z]:)?[\w./\\-]+\.py):\d+(?::\d+)?"
    )
    for text in (stdout, stderr):
        candidates.extend(match.group(1) for match in traceback_pattern.finditer(text))

    root = Path(workspace).resolve() if workspace is not None else None
    normalized: list[str] = []
    for raw in candidates:
        path_text = raw.replace("\\", "/").strip("'\"()[]")
        if not path_text:
            continue
        candidate = Path(path_text)
        if root is not None:
            try:
                resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
                relative = resolved.relative_to(root)
            except (ValueError, OSError):
                continue
            if not resolved.is_file():
                continue
            path_text = relative.as_posix()
        elif candidate.is_absolute() or ".." in candidate.parts:
            continue
        else:
            path_text = candidate.as_posix()
        if path_text not in normalized:
            normalized.append(path_text)
    return normalized


# =============================================================
# Summary
# =============================================================


def build_pytest_summary(
    parsed: dict,
) -> str:

    parts = []

    if (
        parsed[
            "passed"
        ]
    ):

        parts.append(
            (
                f"{parsed['passed']} "
                "passed"
            )
        )

    if (
        parsed[
            "failed"
        ]
    ):

        parts.append(
            (
                f"{parsed['failed']} "
                "failed"
            )
        )

    if (
        parsed[
            "errors"
        ]
    ):

        parts.append(
            (
                f"{parsed['errors']} "
                "errors"
            )
        )

    if (
        parsed[
            "skipped"
        ]
    ):

        parts.append(
            (
                f"{parsed['skipped']} "
                "skipped"
            )
        )

    if not (
        parts
    ):

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


# =============================================================
# LLM Content
# =============================================================


def build_pytest_llm_content(
    parsed: dict,
) -> str:

    sections = [
        (
            "Exit code: "
            f"{parsed['exit_code']}"
        )
    ]

    if (
        parsed.get(
            "output_truncated"
        )
    ):

        sections.append(
            (
                "Sandbox note: pytest "
                "output was truncated."
            )
        )

    if (
        parsed[
            "failed_tests"
        ]
    ):

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

    if (
        parsed[
            "failure_details"
        ]
    ):

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

    if (
        parsed[
            "stderr"
        ]
    ):

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


# =============================================================
# Extract Count
# =============================================================


def _extract_count(
    text: str,
    label: str,
) -> int:

    pattern = (
        rf"(\d+)\s+"
        rf"{re.escape(label)}\b"
    )

    matches = (
        re.findall(
            pattern,
            text,
            re.IGNORECASE,
        )
    )

    if not (
        matches
    ):

        return 0

    return int(
        matches[
            -1
        ]
    )


# =============================================================
# Failed Test Names
# =============================================================


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

    return (
        failed_names
    )


# =============================================================
# Failure Details
# =============================================================


def _failure_detail_lines(
    stdout_lines: list[str],
    max_fail_lines: int,
) -> list[str]:

    detail = []

    capturing = False

    for line in (
        stdout_lines
    ):

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

        if (
            capturing
        ):

            if (
                re.fullmatch(
                    r"\.+",
                    line.strip(),
                )
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

    return (
        detail
    )
