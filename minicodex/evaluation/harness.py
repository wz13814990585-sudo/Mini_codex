"""Evaluation runner for MiniCodex."""

from __future__ import annotations

from collections.abc import (
    Callable,
    Iterable,
)
import time

from ..agent.validation import (
    CompletionGate,
)
from ..agent.routing import TaskIntent

from .checks import (
    EvaluationCheckRunner,
)
from .models import (
    EvaluationCase,
    EvaluationComparison,
    EvaluationResult,
    EvaluationSummary,
)


class EvaluationHarness:
    """
    Run a deterministic benchmark suite against MiniCodex.

    The Harness intentionally does not use an LLM-as-a-judge.

    Success is based on:

        - deterministic workspace checks
        - MiniCodex completion evidence
        - execution constraints
        - runtime errors
    """

    def __init__(
        self,
        *,
        agent_factory: Callable[
            [EvaluationCase],
            object,
        ],
        check_runner: (
            EvaluationCheckRunner
            | None
        ) = None,
        profile: str = "",
        model: str = "",
        run_index: int = 1,
    ):

        self.agent_factory = (
            agent_factory
        )

        self.check_runner = (
            check_runner
            or EvaluationCheckRunner()
        )

        self.completion_gate = (
            CompletionGate()
        )
        self.profile = profile
        self.model = model
        self.run_index = int(run_index)

    # =========================================================
    # Run Suite
    # =========================================================

    def run_suite(
        self,
        *,
        run_name: str,
        cases: Iterable[
            EvaluationCase
        ],
    ) -> EvaluationSummary:

        results = []

        for case in (
            cases
        ):

            results.append(
                self.run_case(
                    case
                )
            )

        return EvaluationSummary(
            run_name=(
                run_name
            ),
            results=(
                results
            ),
        )

    # =========================================================
    # Run One Case
    # =========================================================

    def run_case(
        self,
        case: EvaluationCase,
    ) -> EvaluationResult:

        started = (
            time.perf_counter()
        )

        agent = None

        output = ""

        error = None

        try:

            agent = (
                self.agent_factory(
                    case
                )
            )

            run_kwargs = {}
            benchmark_policy = getattr(agent, "_benchmark_policy", None)
            if benchmark_policy is not None:
                run_kwargs["policy"] = benchmark_policy
            output = str(agent.run(case.prompt, **run_kwargs))

            recorder = getattr(agent, "_benchmark_recorder", None)
            trace_path = getattr(agent, "_benchmark_trace_path", None)
            if recorder is not None and trace_path:
                recorder.save_jsonl(trace_path)

            # Hidden oracle files are intentionally materialized only after
            # the agent has stopped, so no workspace tool can inspect them
            # during task execution.
            materialize_oracle = getattr(agent, "_benchmark_materialize_oracle", None)
            if callable(materialize_oracle):
                materialize_oracle()

        except Exception as e:

            error = (
                f"{type(e).__name__}: "
                f"{e}"
            )

        duration = (
            time.perf_counter()
            - started
        )

        # =====================================================
        # Agent Creation Failed
        # =====================================================

        if (
            agent
            is None
        ):

            return EvaluationResult(
                case_id=(
                    case.case_id
                ),
                passed=False,
                output=(
                    output
                ),
                duration_seconds=(
                    duration
                ),
                error=(
                    error
                ),
                tags=(
                    case.tags
                ),
                run_index=self.run_index,
                category=case.category,
                profile=self.profile,
                model=self.model,
                benchmark_version=case.benchmark_version,
                failure_category="environment_failure",
                failure_reason=error,
            )

        workspace = getattr(
            agent,
            "workspace",
            ".",
        )
        oracle_root = getattr(agent, "_benchmark_oracle_root", None)

        # =====================================================
        # Deterministic Checks
        # =====================================================

        check_results = []

        for check in (
            case.checks
        ):

            check_results.append(
                self.check_runner
                .run(
                    check=check,
                    workspace=workspace,
                    output=output,
                    oracle_root=oracle_root,
                )
            )

        cleanup_oracle = getattr(agent, "_benchmark_cleanup_oracle", None)
        if callable(cleanup_oracle):
            try:
                cleanup_oracle()
            except Exception as exc:
                from .models import CheckResult
                check_results.append(CheckResult(
                    kind="oracle_cleanup",
                    passed=False,
                    description="Hidden oracle cleanup must succeed.",
                    error=f"{type(exc).__name__}: {exc}",
                ))

        checks_passed = all(
            result.passed
            for result
            in check_results
        )

        # Empty check list is valid.
        if not (
            case.checks
        ):

            checks_passed = True

        oracle_checks = len(check_results)
        oracle_passed = checks_passed

        # =====================================================
        # Validation State
        # =====================================================

        validation_pipeline = getattr(
            agent,
            "validation_pipeline",
            None,
        )

        validation_state = getattr(
            validation_pipeline,
            "state",
            None,
        )

        edit_revision = int(
            getattr(
                validation_state,
                "edit_revision",
                0,
            )
            or 0
        )

        has_edit = bool(
            getattr(
                validation_state,
                "has_edit",
                False,
            )
        )

        acceptance_passed = bool(
            getattr(
                validation_state,
                "acceptance_passed",
                False,
            )
        )

        full_passed = bool(
            getattr(
                validation_state,
                "full_passed",
                False,
            )
        )

        completion = (
            self.completion_gate
            .evaluate(
                edit_revision=(
                    edit_revision
                ),
                has_edit=(
                    has_edit
                ),
                acceptance_passed=(
                    acceptance_passed
                ),
                full_validation_passed=(
                    full_passed
                ),
            )
        )
        # Evaluate real agents with the same requirement-aware gate as execution.
        if getattr(agent, "completion_policy", None) is not None:
            completion = agent.completion_policy.evaluate(agent)

        # =====================================================
        # Plan State
        # =====================================================

        plan = getattr(
            agent,
            "active_plan",
            None,
        )

        if (
            plan
            is None
        ):

            plan_completed = True

        else:

            try:

                plan_completed = bool(
                    plan.is_completed()
                )

            except Exception:

                plan_completed = False

        # =====================================================
        # Token Metrics
        # =====================================================

        token_metrics = getattr(
            agent,
            "token_metrics",
            None,
        )

        token_total = getattr(
            token_metrics,
            "total",
            None,
        )

        prompt_tokens = int(
            getattr(
                token_total,
                "prompt_tokens",
                0,
            )
            or 0
        )

        completion_tokens = int(
            getattr(
                token_total,
                "completion_tokens",
                0,
            )
            or 0
        )

        total_tokens = int(
            getattr(
                token_total,
                "total_tokens",
                0,
            )
            or 0
        )

        llm_calls = int(
            getattr(
                token_metrics,
                "call_count",
                0,
            )
            or 0
        )

        execution_metrics = getattr(agent, "execution_metrics", None)

        def metric(name, default=None):
            return getattr(execution_metrics, name, default)

        evidence_history = list(getattr(validation_state, "evidence_history", ()) or ())
        validation_passes = sum(
            getattr(getattr(item, "outcome", None), "value", getattr(item, "outcome", None)) == "passed"
            for item in evidence_history
        )
        validation_failures = sum(
            getattr(getattr(item, "outcome", None), "value", getattr(item, "outcome", None)) == "failed"
            for item in evidence_history
        )
        validation_inconclusive = sum(
            getattr(getattr(item, "outcome", None), "value", getattr(item, "outcome", None)) == "inconclusive"
            for item in evidence_history
        )
        validation_runs = max(len(evidence_history), int(metric("validation_runs", 0) or 0))
        validation_inconclusive += max(0, validation_runs - len(evidence_history))

        # =====================================================
        # Constraints
        # =====================================================

        token_budget_passed = True

        if (
            case.max_total_tokens
            is not None
        ):

            token_budget_passed = (
                total_tokens
                <= case.max_total_tokens
            )

        duration_budget_passed = True

        if (
            case.max_duration_seconds
            is not None
        ):

            duration_budget_passed = (
                duration
                <= case.max_duration_seconds
            )

        route = getattr(agent, "execution_route", None)
        intent = getattr(route, "intent", TaskIntent.MODIFY)
        final_outcome = metric("final_outcome")
        edit_count = int(metric("edit_tool_count", 0) or 0)
        if intent == TaskIntent.INSPECT_ONLY:
            completion_ready = final_outcome == "inspected" and edit_count == 0
        elif intent == TaskIntent.INFORMATIONAL:
            completion_ready = final_outcome == "informational_answer" and edit_count == 0
        else:
            completion_ready = completion.can_complete and plan_completed

        if not (
            case.require_completion_ready
        ):

            completion_ready = True

        # =====================================================
        # Final Evaluation Decision
        # =====================================================

        passed = (
            error
            is None
            and checks_passed
            and completion_ready
            and token_budget_passed
            and duration_budget_passed
        )
        terminal_success = (
            final_outcome in {"edited_and_validated", "already_satisfied"}
            or (final_outcome is None and completion_ready and error is None)
        )
        oracle_infrastructure_failed = any(
            bool(result.error) and not str(result.error).startswith("exit_code=")
            for result in check_results
        )
        false_completion = bool(
            intent == TaskIntent.MODIFY and terminal_success and not oracle_passed
            and not oracle_infrastructure_failed
        )
        repair_attempts = int(metric("repair_attempts", 0) or 0)
        failed_evidence = [
            item for item in evidence_history
            if getattr(getattr(item, "outcome", None), "value", getattr(item, "outcome", None))
            in {"failed", "inconclusive"}
            and int(getattr(item, "edit_revision", 0) or 0) > 0
        ]
        corrective_edit = any(edit_revision > int(getattr(item, "edit_revision", 0) or 0)
                              for item in failed_evidence)
        recovery_entered = bool(failed_evidence and (repair_attempts > 0 or corrective_edit))
        recovery_success = bool(recovery_entered and (repair_attempts > 0 or corrective_edit) and oracle_passed)
        first_targeted = next((
            item for item in evidence_history
            if int(getattr(item, "edit_revision", 0) or 0) > 0
            and getattr(getattr(item, "scope", None), "value", getattr(item, "scope", None))
            in {"targeted", "full"}
        ), None)
        first_pass_success = bool(
            edit_count > 0
            and first_targeted is not None
            and getattr(getattr(first_targeted, "outcome", None), "value",
                        getattr(first_targeted, "outcome", None)) == "passed"
            and edit_revision == int(getattr(first_targeted, "edit_revision", -1))
            and not recovery_entered
            and int(metric("rollback_count", 0) or 0) == 0
            and oracle_passed
        )
        failure_category = self._failure_category(
            passed=passed, error=error, checks_passed=checks_passed,
            completion_ready=completion_ready, edit_count=edit_count,
            validation_state=validation_state, metrics=execution_metrics,
            false_completion=false_completion,
            oracle_infrastructure_failed=oracle_infrastructure_failed,
        )
        failure_reason = self._failure_reason(
            category=failure_category,
            error=error,
            check_results=check_results,
            completion_ready=completion_ready,
            metrics=execution_metrics,
        )

        return EvaluationResult(
            case_id=(
                case.case_id
            ),
            passed=(
                passed
            ),
            output=(
                output
            ),
            checks=(
                check_results
            ),
            completion_status=(
                completion.status.value
            ),
            plan_completed=(
                plan_completed
            ),
            edit_revision=(
                edit_revision
            ),
            acceptance_passed=(
                acceptance_passed
            ),
            full_validation_passed=(
                full_passed
            ),
            prompt_tokens=(
                prompt_tokens
            ),
            completion_tokens=(
                completion_tokens
            ),
            total_tokens=(
                total_tokens
            ),
            llm_calls=(
                llm_calls
            ),
            execution_mode=metric("execution_mode"),
            intent=metric("intent", getattr(intent, "value", intent)),
            tool_call_count=int(metric("tool_call_count", 0) or 0),
            inspection_tool_count=int(metric("inspection_tool_count", 0) or 0),
            edit_tool_count=int(metric("edit_tool_count", 0) or 0),
            validation_tool_count=int(metric("validation_tool_count", 0) or 0),
            calls_before_first_edit=metric("calls_before_first_edit"),
            calls_before_first_validation=metric("calls_before_first_validation"),
            action_required_trigger_count=int(
                metric("action_required_trigger_count", 0) or 0
            ),
            replan_count=int(metric("replan_count", 0) or 0),
            rollback_count=int(metric("rollback_count", 0) or 0),
            max_steps_exhausted=bool(metric("max_steps_exhausted", False)),
            final_outcome=final_outcome,
            final_completion_reason=metric("final_completion_reason"),
            final_reason_code=metric("final_reason_code"),
            false_completion=false_completion,
            wrong_edit=bool(intent != TaskIntent.MODIFY and edit_count > 0),
            routing_llm_calls=int(metric("routing_llm_calls", 0) or 0),
            requirements_llm_calls=int(metric("requirements_llm_calls", 0) or 0),
            semantic_judge_llm_calls=int(metric("semantic_judge_llm_calls", 0) or 0),
            control_llm_calls=(
                int(metric("routing_llm_calls", 0) or 0)
                + int(metric("requirements_llm_calls", 0) or 0)
                + int(metric("semantic_judge_llm_calls", 0) or 0)
            ),
            mode_escalations=int(metric("mode_escalations", 0) or 0),
            late_plan_activations=int(metric("late_plan_activations", 0) or 0),
            repair_attempts=repair_attempts,
            flaky_reruns=int(metric("flaky_reruns", 0) or 0),
            premature_rollbacks_prevented=int(
                metric("premature_rollbacks_prevented", 0) or 0
            ),
            repeated_action_count=int(metric("repeated_action_count", 0) or 0),
            repeated_action_rate=float(metric("repeated_action_rate", 0.0) or 0.0),
            no_progress_detections=int(metric("no_progress_detections", 0) or 0),
            recovery_successes=int(metric("recovery_successes", 0) or 0),
            time_to_first_edit=metric("time_to_first_edit"),
            inspections_before_first_edit=metric("inspections_before_first_edit"),
            searches_before_first_edit=int(metric("searches_before_first_edit", 0)),
            redundant_reads=int(metric("redundant_reads", 0)),
            redundant_searches=int(metric("redundant_searches", 0)),
            wrong_validation_target=bool(metric("wrong_validation_target_count", 0)),
            failure_category=failure_category,
            cost_usd=metric("cost_usd"),
            duration_seconds=(
                duration
            ),
            error=(
                error
            ),
            tags=(
                case.tags
            ),
            run_index=self.run_index,
            category=case.category,
            profile=self.profile,
            model=self.model,
            benchmark_version=case.benchmark_version,
            first_pass_success=first_pass_success,
            oracle_checks=oracle_checks,
            oracle_passed=oracle_passed,
            agent_steps=int(metric("agent_steps", 0) or 0),
            llm_call_count=(llm_calls + int(metric("routing_llm_calls", 0) or 0)
                            + int(metric("requirements_llm_calls", 0) or 0)
                            + int(metric("semantic_judge_llm_calls", 0) or 0)),
            main_agent_llm_calls=int(metric("agent_steps", 0) or 0),
            validation_runs=validation_runs,
            validation_passes=validation_passes,
            validation_failures=validation_failures,
            validation_inconclusive=validation_inconclusive,
            recovery_entered=recovery_entered,
            recovery_success=recovery_success,
            total_control_llm_calls=(max(0, llm_calls - int(metric("agent_steps", 0) or 0))
                                     + int(metric("routing_llm_calls", 0) or 0)
                                     + int(metric("requirements_llm_calls", 0) or 0)
                                     + int(metric("semantic_judge_llm_calls", 0) or 0)),
            other_control_llm_calls=max(0, llm_calls - int(metric("agent_steps", 0) or 0)),
            failure_reason=failure_reason,
            trace_path=getattr(agent, "_benchmark_trace_path", None),
        )

    @staticmethod
    def _failure_category(*, passed, error, checks_passed, completion_ready, edit_count,
                          validation_state, metrics, false_completion=False,
                          oracle_infrastructure_failed=False):
        if passed:
            return None
        if error:
            return "environment_failure"
        if oracle_infrastructure_failed:
            return "environment_failure"
        if false_completion:
            return "false_completion"
        reason = str(getattr(metrics, "final_reason_code", "") or "")
        if bool(getattr(metrics, "wrong_edit", False)):
            return "wrong_file"
        if "routing" in reason:
            return "routing_failure"
        if "requirement" in reason:
            return "requirement_failure"
        if "spec" in reason or "binding" in reason:
            return "spec_binding_failure"
        if "capability" in reason:
            return "capability_missing"
        if "edit" in reason and "fail" in reason:
            return "edit_failure"
        if getattr(metrics, "max_steps_exhausted", False):
            return "max_steps"
        if int(getattr(metrics, "wrong_validation_target_count", 0) or 0) > 0:
            return "wrong_validation_target"
        if not edit_count:
            return "no_tool_loop" if int(getattr(metrics, "tool_call_count", 0) or 0) == 0 else "no_edit"
        if int(getattr(metrics, "repair_attempts", 0) or 0) > 0:
            return "recovery_failure"
        if int(getattr(metrics, "redundant_reads", 0) or 0) + int(getattr(metrics, "redundant_searches", 0) or 0) > 0:
            return "repeated_inspection"
        if not completion_ready:
            return "wrong_validation_target"
        if not checks_passed:
            return "oracle_failure"
        return "unknown"

    @staticmethod
    def _failure_reason(*, category, error, check_results, completion_ready, metrics):
        if category is None:
            return None
        if error:
            return error
        failed = [result for result in check_results if not result.passed]
        if failed:
            item = failed[0]
            return item.error or item.description
        reason = getattr(metrics, "final_completion_reason", None)
        if reason:
            return str(reason)
        if not completion_ready:
            return "Agent completion evidence was incomplete."
        return category.replace("_", " ")


# =============================================================
# Compare Two Evaluation Runs
# =============================================================


def compare_summaries(
    baseline: EvaluationSummary,
    candidate: EvaluationSummary,
) -> EvaluationComparison:

    baseline_by_id = {
        result.case_id: result
        for result
        in baseline.results
    }

    candidate_by_id = {
        result.case_id: result
        for result
        in candidate.results
    }

    common_case_ids = (
        sorted(
            set(
                baseline_by_id
            )
            & set(
                candidate_by_id
            )
        )
    )

    improved = []

    regressed = []

    unchanged = []

    for case_id in (
        common_case_ids
    ):

        before = (
            baseline_by_id[
                case_id
            ]
        )

        after = (
            candidate_by_id[
                case_id
            ]
        )

        if (
            not before.passed
            and after.passed
        ):

            improved.append(
                case_id
            )

        elif (
            before.passed
            and not after.passed
        ):

            regressed.append(
                case_id
            )

        else:

            unchanged.append(
                case_id
            )

    return EvaluationComparison(
        baseline_run=(
            baseline.run_name
        ),
        candidate_run=(
            candidate.run_name
        ),
        baseline_success_rate=(
            baseline.success_rate
        ),
        candidate_success_rate=(
            candidate.success_rate
        ),
        success_rate_delta=(
            candidate.success_rate
            - baseline.success_rate
        ),
        baseline_average_tokens=(
            baseline.average_tokens
        ),
        candidate_average_tokens=(
            candidate.average_tokens
        ),
        average_tokens_delta=(
            candidate.average_tokens
            - baseline.average_tokens
        ),
        baseline_average_duration_seconds=(
            baseline.average_duration_seconds
        ),
        candidate_average_duration_seconds=(
            candidate.average_duration_seconds
        ),
        average_duration_delta_seconds=(
            candidate.average_duration_seconds
            - baseline.average_duration_seconds
        ),
        baseline_average_edit_revisions=(
            baseline.average_edit_revisions
        ),
        candidate_average_edit_revisions=(
            candidate.average_edit_revisions
        ),
        average_edit_revisions_delta=(
            candidate.average_edit_revisions
            - baseline.average_edit_revisions
        ),
        improved_cases=tuple(
            improved
        ),
        regressed_cases=tuple(
            regressed
        ),
        unchanged_cases=tuple(
            unchanged
        ),
    )
