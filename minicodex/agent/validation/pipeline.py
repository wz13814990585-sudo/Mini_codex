from dataclasses import replace
import ast
from pathlib import Path
import shlex

from ...tools.results import ToolResult
from .evidence import (ValidationOutcome, ValidationScope, ValidationPurpose,
                       ValidationEvidence, FailureDelta, FailureComparison)
from .ledger import ValidationLedger


class ValidationPipeline:

    def __init__(
        self,
    ):

        self.state = (
            ValidationLedger()
        )

    # =========================================================
    # Reset
    # =========================================================

    def reset(
        self,
    ) -> None:

        self.state.reset()

    # =========================================================
    # Record Edit
    # =========================================================

    def record_edit(
        self,
        *, owned: bool = True,
    ) -> int:

        return self.state.record_edit(owned=owned)

    # =========================================================
    # Observe Tool Result
    # =========================================================

    def observe(
        self,
        tool_name: str,
        arguments: dict,
        result: ToolResult,
        capabilities: frozenset[str] | None = None,
    ) -> ValidationEvidence | None:

        original_name = tool_name
        if capabilities:
            if "test.run" in capabilities:
                tool_name = "run_tests"
            elif capabilities & {"validation.browser", "service.validate"}:
                tool_name = "validate_browser_app"
            elif "validation.static_web" in capabilities:
                tool_name = "validate_static_web"
            elif "process.run" in capabilities:
                tool_name = "run_command"

        if tool_name in {"validate_static_web", "validate_browser_app"}:

            evidence = self._from_static_web(
                arguments=arguments,
                result=result,
                tool_name=tool_name,
            )

        elif tool_name == "run_command":

            if (
                str(
                    arguments.get(
                        "purpose",
                        "diagnostic",
                    )
                ).strip().lower()
                not in {"acceptance", "regression"}
            ):
                return None

            evidence = self._from_run_command(
                arguments=arguments,
                result=result,
            )

        elif tool_name == "run_tests":

            evidence = self._from_run_tests(
                arguments=arguments,
                result=result,
            )

        else:
            return None

        if result.data.get("workspace_changed_during_validation"):
            evidence = replace(evidence, outcome=ValidationOutcome.INCONCLUSIVE, failed_count=None,
                               summary="Workspace changed during validation; rerun against the current revision.")
        check_id = str(arguments.get("validation_check", ""))
        candidates = [c for c in self.state.plan.checks if c.purpose == evidence.purpose]
        # Only a genuinely single-outcome task can omit the explicit binding.
        if not check_id and len(candidates) == 1:
            check_id = candidates[0].id
        check = next((c for c in candidates if c.id == check_id), None)
        strength = 2
        if tool_name == "validate_static_web":
            strength = int(result.data.get("evidence_strength", 0))
        elif tool_name == "validate_browser_app":
            strength = int(result.data.get("evidence_strength", 5))
        if tool_name in {"validate_static_web", "validate_browser_app"}:
            import hashlib
            import json
            specification = {k: v for k, v in arguments.items()
                             if k not in {"path", "validation_check", "purpose", "timeout", "port"}}
            if specification:
                digest = hashlib.sha256(json.dumps(specification, sort_keys=True).encode()).hexdigest()[:16]
                evidence = replace(evidence, details={**evidence.details, "target_identity": f"{evidence.path}#{digest}"})
        if tool_name == "run_command":
            strength = self._command_strength(str(arguments.get("command", "")))
            if check and check.capability == "process.run" and check.target == evidence.path:
                strength = int(check.strength)
        evidence = replace(evidence, tool_name=original_name, check_id=check.id if check else "",
                           requirement_ids=check.requirement_ids if check else (), strength=strength,
                           capability="service.validate" if "service.validate" in (capabilities or ()) else {"run_tests": "test.run", "run_command": "process.run", "validate_static_web": "validation.static_web", "validate_browser_app": "validation.browser"}.get(tool_name, ""),
                           agent_test_only=bool(result.data.get("agent_test_only", False)))
        evidence = self.state.record(evidence)

        # Expose one normalized validation result shape to downstream traces,
        # summaries, and evaluation code regardless of the concrete tool.
        result.data.update(
            {
                "purpose": evidence.purpose.value,
                "outcome": evidence.outcome.value,
                "path": evidence.path,
                "failed_count": evidence.failed_count,
                "validation_summary": evidence.summary,
                "validation_key": evidence.validation_key,
                "failure_ids": list(evidence.failure_ids),
                "unstable": evidence.unstable,
                "validation_check": evidence.check_id,
                "requirement_ids": list(evidence.requirement_ids),
                "evidence_strength": evidence.strength,
                "agent_test_only": evidence.agent_test_only,
            }
        )

        return evidence

    @staticmethod
    def _command_strength(command: str) -> int:
        """Recognize assertions/runners, not success-shaped words in stdout commands."""
        try:
            argv = shlex.split(command)
        except ValueError:
            return -1
        if not argv or any(part in {";", "&&", "||", "|", "&"} for part in argv):
            return -1
        executable = Path(argv[0]).name
        if executable.startswith("python"):
            if any(flag.startswith("-O") for flag in argv[1:]):
                return -1  # optimized Python removes assertions
            if "-c" in argv:
                try:
                    tree = ast.parse(argv[argv.index("-c") + 1])
                except (SyntaxError, IndexError):
                    return -1
                assertions = [node.test for node in ast.walk(tree) if isinstance(node, ast.Assert)]
                return 2 if any(not isinstance(node, ast.Constant) and any(
                    isinstance(child, (ast.Call, ast.Name, ast.Attribute, ast.Subscript))
                    for child in ast.walk(node)) for node in assertions) else -1
            if len(argv) > 2 and argv[1] == "-m" and argv[2] in {"pytest", "unittest"}:
                return 2
            if len(argv) > 1 and argv[1].endswith(".py") and any(word in Path(argv[1]).stem for word in ("test", "check", "validate")):
                return 2
        if executable in {"pytest", "jest", "vitest"}:
            return 2
        if executable in {"npm", "pnpm", "yarn"} and argv[1:] and argv[1] in {"test", "run"}:
            script = argv[2] if argv[1] == "run" and len(argv) > 2 else argv[1]
            return 2 if script in {"test", "check", "validate"} else -1
        if executable in {"test", "[", "grep"}:
            return 0
        return -1

    def _from_static_web(
        self,
        *,
        arguments: dict,
        result: ToolResult,
        tool_name: str = "validate_static_web",
    ) -> ValidationEvidence:
        outcome_value = str(
            result.data.get(
                "outcome",
                "inconclusive",
            )
        ).strip().lower()
        outcome = {
            "passed": ValidationOutcome.PASSED,
            "failed": ValidationOutcome.FAILED,
        }.get(
            outcome_value,
            ValidationOutcome.INCONCLUSIVE,
        )
        errors = result.data.get("errors", [])
        failure_count = (
            len(errors)
            if isinstance(errors, list)
            else 1
        )

        if not result.success:
            outcome = ValidationOutcome.INCONCLUSIVE
            failure_count = 0

        return ValidationEvidence(
            tool_name=tool_name,
            execution_succeeded=result.success,
            outcome=outcome,
            scope=ValidationScope.TARGETED,
            purpose=ValidationPurpose.ACCEPTANCE,
            edit_revision=self.state.edit_revision,
            failed=(
                failure_count
                if outcome == ValidationOutcome.FAILED
                else 0
            ),
            failed_count=(
                failure_count
                if outcome == ValidationOutcome.FAILED
                else (
                    0
                    if outcome == ValidationOutcome.PASSED
                    else None
                )
            ),
            path=str(arguments.get("path", "")).strip(),
            summary=result.summary,
            details=dict(result.data),
        )

    def _from_run_command(
        self,
        *,
        arguments: dict,
        result: ToolResult,
    ) -> ValidationEvidence:
        """Normalize an explicitly labelled acceptance command."""

        command = str(
            arguments.get(
                "command",
                "",
            )
        ).strip()

        if not result.success:
            outcome = ValidationOutcome.INCONCLUSIVE
            execution_succeeded = False
            failed_count = None
        elif result.data.get("command_succeeded") is True:
            outcome = ValidationOutcome.PASSED
            execution_succeeded = True
            failed_count = 0
        elif result.data.get("command_succeeded") is False:
            outcome = ValidationOutcome.FAILED
            execution_succeeded = True
            failed_count = 1
        else:
            outcome = ValidationOutcome.INCONCLUSIVE
            execution_succeeded = True
            failed_count = None

        return ValidationEvidence(
            tool_name="run_command",
            execution_succeeded=execution_succeeded,
            outcome=outcome,
            scope=ValidationScope.TARGETED,
            purpose=self._validation_purpose(arguments.get("purpose", "acceptance")),
            edit_revision=self.state.edit_revision,
            failed=(
                1
                if outcome == ValidationOutcome.FAILED
                else 0
            ),
            failed_count=failed_count,
            path=command,
            summary=result.summary,
        )

    # =========================================================
    # Record Evidence
    # =========================================================

    def failure_delta(self, evidence: ValidationEvidence) -> FailureDelta:
        comparison = self.compare_baseline(evidence)
        if comparison is None:
            return FailureDelta.UNKNOWN
        if comparison.new:
            return FailureDelta.NEW_FAILURE
        if comparison.resolved:
            return FailureDelta.RESOLVED_FAILURE
        if comparison.persisting:
            return (
                FailureDelta.PRE_EXISTING_FAILURE
                if evidence.edit_revision > 0
                else FailureDelta.PERSISTING_FAILURE
            )
        return FailureDelta.UNKNOWN

    def compare_baseline(self, evidence: ValidationEvidence) -> FailureComparison | None:
        baseline = self.state.baseline_by_key.get(evidence.validation_key)
        if baseline is None:
            return None
        before = set(baseline.failure_ids)
        after = set(evidence.failure_ids)
        return FailureComparison(
            new=tuple(sorted(after - before)),
            resolved=tuple(sorted(before - after)),
            persisting=tuple(sorted(before & after)),
        )

    # =========================================================
    # Next Action
    # =========================================================


    # =========================================================
    # Normalize RunTests
    # =========================================================

    def _from_run_tests(
        self,
        *,
        arguments: dict,
        result: ToolResult,
    ) -> ValidationEvidence:

        path = str(
            arguments.get(
                "path",
                ".",
            )
        ).strip()

        purpose = (
            self._validation_purpose(
                arguments.get(
                    "purpose",
                    "regression",
                )
            )
        )

        scope = (
            self._test_scope(
                path
            )
        )

        # =====================================================
        # Tool Execution Failure
        # =====================================================

        if not result.success:

            return ValidationEvidence(
                tool_name="run_tests",
                execution_succeeded=False,
                outcome=(
                    ValidationOutcome
                    .INCONCLUSIVE
                ),
                scope=scope,
                purpose=purpose,
                edit_revision=(
                    self.state
                    .edit_revision
                ),
                failed_count=None,
                path=path,
                summary=(
                    result.summary
                ),
                environment_failure=True,
                details=dict(result.data),
            )

        tests_passed = (
            result.data.get(
                "tests_passed"
            )
        )

        passed = (
            self._safe_int(
                result.data.get(
                    "passed",
                    0,
                )
            )
        )

        failed = (
            self._safe_int(
                result.data.get(
                    "failed",
                    0,
                )
            )
        )

        errors = (
            self._safe_int(
                result.data.get(
                    "errors",
                    0,
                )
            )
        )

        skipped = (
            self._safe_int(
                result.data.get(
                    "skipped",
                    0,
                )
            )
        )

        # =====================================================
        # Passed
        # =====================================================

        if (
            tests_passed
            is True
        ):

            return ValidationEvidence(
                tool_name="run_tests",
                execution_succeeded=True,
                outcome=(
                    ValidationOutcome
                    .PASSED
                ),
                scope=scope,
                purpose=purpose,
                edit_revision=(
                    self.state
                    .edit_revision
                ),
                passed=passed,
                failed=failed,
                errors=errors,
                skipped=skipped,
                failed_count=0,
                path=path,
                summary=(
                    result.summary
                ),
                failure_ids=tuple(dict.fromkeys(tuple(result.data.get("failed_tests", ()) or ()) + tuple(result.data.get("failure_fingerprints", ()) or ()))),
                details=dict(result.data),
            )

        # =====================================================
        # Failed
        # =====================================================

        failure_total = (
            failed
            + errors
        )

        if (
            failure_total
            > 0
        ):

            return ValidationEvidence(
                tool_name="run_tests",
                execution_succeeded=True,
                outcome=(
                    ValidationOutcome
                    .FAILED
                ),
                scope=scope,
                purpose=purpose,
                edit_revision=(
                    self.state
                    .edit_revision
                ),
                passed=passed,
                failed=failed,
                errors=errors,
                skipped=skipped,
                failed_count=(
                    failure_total
                ),
                path=path,
                summary=(
                    result.summary
                ),
                failure_ids=tuple(dict.fromkeys(tuple(result.data.get("failed_tests", ()) or ()) + tuple(result.data.get("failure_fingerprints", ()) or ()))),
                details=dict(result.data),
            )

        # =====================================================
        # Inconclusive
        # =====================================================

        return ValidationEvidence(
            tool_name="run_tests",
            execution_succeeded=True,
            outcome=(
                ValidationOutcome
                .INCONCLUSIVE
            ),
            scope=scope,
            purpose=purpose,
            edit_revision=(
                self.state
                .edit_revision
            ),
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            failed_count=None,
            path=path,
            summary=(
                result.summary
            ),
            failure_ids=tuple(dict.fromkeys(tuple(result.data.get("failed_tests", ()) or ()) + tuple(result.data.get("failure_fingerprints", ()) or ()))),
            details=dict(result.data),
        )

    # =========================================================
    # Scope
    # =========================================================

    @staticmethod
    def _test_scope(
        path: str,
    ) -> ValidationScope:

        normalized = (
            path.strip()
        )

        if normalized in {
            "",
            ".",
            "./",
        }:

            return (
                ValidationScope.FULL
            )

        if normalized:

            return (
                ValidationScope.TARGETED
            )

        return (
            ValidationScope.UNKNOWN
        )

    # =========================================================
    # Purpose
    # =========================================================

    @staticmethod
    def _validation_purpose(
        value,
    ) -> ValidationPurpose:
        """
        Unknown purpose values degrade to regression.

        This is conservative:
        an invalid value can never fabricate acceptance
        evidence.
        """

        normalized = (
            str(value)
            .strip()
            .lower()
        )

        if (
            normalized
            == ValidationPurpose.ACCEPTANCE.value
        ):

            return (
                ValidationPurpose.ACCEPTANCE
            )

        return (
            ValidationPurpose.REGRESSION
        )

    # =========================================================
    # Safe Integer
    # =========================================================

    @staticmethod
    def _safe_int(
        value,
    ) -> int:

        try:

            return int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):

            return 0
