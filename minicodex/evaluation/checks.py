"""Deterministic evaluation checks."""

from __future__ import annotations

from pathlib import Path

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