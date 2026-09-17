"""Deterministic evaluation checks."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

from .models import (
    CheckResult,
    EvaluationCheck,
)


class EvaluationCheckRunner:
    """
    Execute deterministic evaluation checks.

    Evaluation evidence must come from real outputs and the
    workspace, not from the Agent claiming that it succeeded.
    """

    SUPPORTED_KINDS = {
        "file_exists",
        "file_not_exists",
        "file_contains",
        "file_not_contains",
        "output_contains",
        "output_not_contains",
        "command_succeeds",
        "python_assertion",
        "pytest_passes",
    }

    def run(
        self,
        *,
        check: EvaluationCheck,
        workspace,
        output: str,
    ) -> CheckResult:

        if (
            check.kind
            not in self.SUPPORTED_KINDS
        ):

            return CheckResult(
                kind=(
                    check.kind
                ),
                passed=False,
                description=(
                    check.description
                    or (
                        "Unsupported evaluation "
                        f"check: {check.kind}"
                    )
                ),
                path=(
                    check.path
                ),
                expected=(
                    check.expected
                ),
                error=(
                    "unsupported_check"
                ),
            )

        workspace_path = (
            Path(
                workspace
            )
            .resolve()
        )

        if check.kind in {"command_succeeds", "python_assertion", "pytest_passes"}:
            return self._run_process_check(check, workspace_path)

        # =====================================================
        # Output Checks
        # =====================================================

        if (
            check.kind
            in {
                "output_contains",
                "output_not_contains",
            }
        ):

            return (
                self._run_output_check(
                    check=check,
                    output=output,
                )
            )

        # =====================================================
        # File Path Required
        # =====================================================

        if (
            check.path
            is None
            or not check.path.strip()
        ):

            return CheckResult(
                kind=(
                    check.kind
                ),
                passed=False,
                description=(
                    check.description
                    or "File check requires a path."
                ),
                path=(
                    check.path
                ),
                expected=(
                    check.expected
                ),
                error=(
                    "missing_path"
                ),
            )

        target = (
            (
                workspace_path
                / check.path
            )
            .resolve()
        )

        try:

            target.relative_to(
                workspace_path
            )

        except ValueError:

            return CheckResult(
                kind=(
                    check.kind
                ),
                passed=False,
                description=(
                    check.description
                    or (
                        "Evaluation check path "
                        "escaped the workspace."
                    )
                ),
                path=(
                    check.path
                ),
                expected=(
                    check.expected
                ),
                error=(
                    "workspace_escape"
                ),
            )

        # =====================================================
        # Exists
        # =====================================================

        if (
            check.kind
            == "file_exists"
        ):

            exists = (
                target.is_file()
            )

            return CheckResult(
                kind=(
                    check.kind
                ),
                passed=(
                    exists
                ),
                description=(
                    check.description
                    or (
                        f"File '{check.path}' "
                        "should exist."
                    )
                ),
                path=(
                    check.path
                ),
                actual=(
                    str(
                        exists
                    )
                ),
            )

        # =====================================================
        # Not Exists
        # =====================================================

        if (
            check.kind
            == "file_not_exists"
        ):

            exists = (
                target.exists()
            )

            return CheckResult(
                kind=(
                    check.kind
                ),
                passed=(
                    not exists
                ),
                description=(
                    check.description
                    or (
                        f"File '{check.path}' "
                        "should not exist."
                    )
                ),
                path=(
                    check.path
                ),
                actual=(
                    str(
                        exists
                    )
                ),
            )

        # =====================================================
        # Content Checks
        # =====================================================

        if not (
            target.is_file()
        ):

            return CheckResult(
                kind=(
                    check.kind
                ),
                passed=False,
                description=(
                    check.description
                    or (
                        f"File '{check.path}' "
                        "could not be checked."
                    )
                ),
                path=(
                    check.path
                ),
                expected=(
                    check.expected
                ),
                error=(
                    "file_missing"
                ),
            )

        try:

            content = (
                target.read_text(
                    encoding="utf-8"
                )
            )

        except Exception as e:

            return CheckResult(
                kind=(
                    check.kind
                ),
                passed=False,
                description=(
                    check.description
                    or (
                        f"File '{check.path}' "
                        "could not be read."
                    )
                ),
                path=(
                    check.path
                ),
                expected=(
                    check.expected
                ),
                error=(
                    f"{type(e).__name__}: "
                    f"{e}"
                ),
            )

        expected = (
            check.expected
            or ""
        )

        if (
            check.kind
            == "file_contains"
        ):

            passed = (
                expected
                in content
            )

        else:

            passed = (
                expected
                not in content
            )

        return CheckResult(
            kind=(
                check.kind
            ),
            passed=(
                passed
            ),
            description=(
                check.description
                or (
                    f"Check {check.kind} "
                    f"for '{check.path}'."
                )
            ),
            path=(
                check.path
            ),
            expected=(
                expected
            ),
        )

    # =========================================================
    # Output Check
    # =========================================================

    @staticmethod
    def _run_output_check(
        *,
        check: EvaluationCheck,
        output: str,
    ) -> CheckResult:

        expected = (
            check.expected
            or ""
        )

        if (
            check.kind
            == "output_contains"
        ):

            passed = (
                expected
                in output
            )

        else:

            passed = (
                expected
                not in output
            )

        return CheckResult(
            kind=(
                check.kind
            ),
            passed=(
                passed
            ),
            description=(
                check.description
                or (
                    f"Check {check.kind} "
                    "against Agent output."
                )
            ),
            expected=(
                expected
            ),
        )

    @staticmethod
    def _run_process_check(check: EvaluationCheck, workspace: Path) -> CheckResult:
        if check.kind == "python_assertion":
            # Avoid benchmark results being contaminated by a stale timestamp-
            # based bytecode cache after an agent edits a fixture rapidly.
            argv = [sys.executable, "-B", "-c", check.command or check.expected or ""]
        elif check.kind == "pytest_passes":
            target = check.path or check.command or "benchmark_oracle"
            argv = [sys.executable, "-m", "pytest", "-q", target]
        else:
            import shlex
            try:
                argv = shlex.split(check.command or check.expected or "")
            except ValueError:
                argv = []
        if not argv:
            return CheckResult(check.kind, False, check.description or "Oracle command is missing.", error="missing_command")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, (str(workspace / "src"), str(workspace), os.environ.get("PYTHONPATH", ""))))}
        try:
            completed = subprocess.run(argv, cwd=workspace, env=env, text=True, capture_output=True,
                                       timeout=check.timeout_seconds or 15, check=False)
            passed = completed.returncode == 0
            actual = (completed.stdout + completed.stderr)[-2000:]
            return CheckResult(check.kind, passed, check.description or f"Oracle {check.kind} should pass.",
                               path=check.path, expected=check.expected, actual=actual,
                               error=None if passed else f"exit_code={completed.returncode}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CheckResult(check.kind, False, check.description or f"Oracle {check.kind} could not run.",
                               path=check.path, error=f"{type(exc).__name__}: {exc}")
