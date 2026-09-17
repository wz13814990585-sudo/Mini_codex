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

            output = str(
                agent.run(
                    case.prompt
                )
            )

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
        failure_category = self._failure_category(
            passed=passed, error=error, checks_passed=checks_passed,
            completion_ready=completion_ready, edit_count=edit_count,
            validation_state=validation_state, metrics=execution_metrics,
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
            false_completion=bool(
                intent == TaskIntent.MODIFY
                and final_outcome in {"edited_and_validated", "already_satisfied"}
                and (not completion.can_complete or not checks_passed)
            ),
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
            repair_attempts=int(metric("repair_attempts", 0) or 0),
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
        )

    @staticmethod
    def _failure_category(*, passed, error, checks_passed, completion_ready, edit_count, validation_state, metrics):
        if passed:
            return None
        if error:
            return "environment_failure"
        if not checks_passed and completion_ready:
            return "false_completion"
        if not edit_count:
            return "no_edit"
        reason = str(getattr(metrics, "final_reason_code", "") or "")
        if "capability" in reason:
            return "capability_missing"
        if getattr(metrics, "max_steps_exhausted", False):
            return "max_steps"
        if int(getattr(metrics, "redundant_reads", 0) or 0) + int(getattr(metrics, "redundant_searches", 0) or 0) > 0:
            return "repeated_inspection"
        if not completion_ready:
            return "validation_target_failure"
        return "oracle_failure"


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
