"""Structured evaluation models for MiniCodex."""

from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from pathlib import Path
import json
import statistics


FAILURE_CATEGORIES = (
    "routing_failure",
    "requirement_failure",
    "planning_failure",
    "target_location_failure",
    "wrong_file_edit",
    "unauthorized_edit",
    "repeated_reconnaissance",
    "no_progress",
    "no_tool_loop",
    "tool_error",
    "edit_failure",
    "spec_binding_failure",
    "wrong_validation_target",
    "validation_failure",
    "regression_failure",
    "capability_missing",
    "environment_failure",
    "recovery_failure",
    "false_completion",
    "max_steps_exhausted",
    "oracle_failure",
    "unknown",
)


# =============================================================
# Evaluation Check
# =============================================================


@dataclass(frozen=True)
class EvaluationCheck:

    kind: str

    expected: str | None = None

    path: str | None = None

    description: str | None = None

    # Independent oracle payload.  These fields are deliberately not inferred
    # from agent output or its validation ledger.
    command: str | None = None
    timeout_seconds: float | None = None


# =============================================================
# Check Result
# =============================================================


@dataclass(frozen=True)
class CheckResult:

    kind: str

    passed: bool

    description: str

    path: str | None = None

    expected: str | None = None

    actual: str | None = None

    error: str | None = None


# =============================================================
# Evaluation Case
# =============================================================


@dataclass(frozen=True)
class EvaluationCase:

    case_id: str

    prompt: str

    checks: tuple[
        EvaluationCheck,
        ...,
    ] = ()

    # Editing tasks should usually require the same completion
    # evidence that normal MiniCodex execution requires.
    require_completion_ready: bool = True

    max_total_tokens: int | None = None

    max_duration_seconds: float | None = None

    tags: tuple[
        str,
        ...,
    ] = ()

    category: str = "modify"

    benchmark_version: str = ""

    # Optional deterministic benchmark edit-scope contract.  An empty tuple
    # deliberately disables strict wrong-file measurement for ambiguous tasks.
    expected_edit_paths: tuple[str, ...] = ()
    allowed_edit_paths: tuple[str, ...] = ()


# =============================================================
# Evaluation Result
# =============================================================


@dataclass
class EvaluationResult:

    case_id: str

    passed: bool

    output: str

    checks: list[
        CheckResult
    ] = field(
        default_factory=list
    )

    completion_status: str | None = None

    plan_completed: bool = False

    edit_revision: int = 0

    acceptance_passed: bool = False

    full_validation_passed: bool = False

    prompt_tokens: int = 0

    completion_tokens: int = 0

    total_tokens: int = 0

    llm_calls: int = 0

    execution_mode: str | None = None

    intent: str | None = None

    tool_call_count: int = 0

    inspection_tool_count: int = 0

    edit_tool_count: int = 0

    validation_tool_count: int = 0

    calls_before_first_edit: int | None = None

    calls_before_first_validation: int | None = None

    action_required_trigger_count: int = 0

    replan_count: int = 0

    rollback_count: int = 0

    max_steps_exhausted: bool = False

    final_outcome: str | None = None

    final_completion_reason: str | None = None

    final_reason_code: str | None = None

    false_completion: bool = False

    unauthorized_edit: bool = False
    wrong_file_edit: bool = False
    routing_llm_calls: int = 0
    requirements_llm_calls: int = 0
    semantic_judge_llm_calls: int = 0
    control_llm_calls: int = 0
    mode_escalations: int = 0
    late_plan_activations: int = 0
    repair_attempts: int = 0
    flaky_reruns: int = 0
    premature_rollbacks_prevented: int = 0
    repeated_action_count: int = 0
    repeated_action_rate: float = 0.0
    no_progress_detections: int = 0
    recovery_successes: int = 0
    time_to_first_edit: float | None = None
    inspections_before_first_edit: int | None = None
    searches_before_first_edit: int = 0
    redundant_reads: int = 0
    redundant_searches: int = 0
    wrong_validation_target: bool = False
    failure_category: str | None = None
    terminal_failure_category: str | None = None
    contributing_signals: tuple[str, ...] = ()
    cost_usd: float | None = None

    duration_seconds: float = 0.0

    error: str | None = None

    tags: tuple[
        str,
        ...,
    ] = ()

    # Benchmark identity and repeatability.
    run_index: int = 1
    category: str = ""
    profile: str = ""
    model: str = ""
    benchmark_version: str = ""

    # Independent-oracle and execution semantics.
    first_pass_success: bool = False
    oracle_checks: int = 0
    oracle_passed: bool = False
    agent_steps: int = 0
    executed_tool_turn_count: int = 0
    ghost_step_count: int = 0
    ghost_step_rate: float = 0.0
    blocked_tool_selection_count: int = 0
    productive_step_count: int = 0
    text_only_step_count: int = 0
    llm_call_count: int = 0
    main_agent_llm_calls: int = 0
    validation_runs: int = 0
    validation_passes: int = 0
    validation_failures: int = 0
    validation_inconclusive: int = 0
    recovery_entered: bool = False
    recovery_success: bool = False
    total_control_llm_calls: int = 0
    other_control_llm_calls: int = 0
    failed_tool_call_count: int = 0
    failed_tool_call_rate: float = 0.0
    failure_reason: str | None = None
    trace_path: str | None = None

    def to_dict(
        self,
    ) -> dict:

        data = asdict(
            self
        )

        # ``passed`` is the long-standing EvaluationHarness field.  Raw
        # Benchmark V1 rows also expose the domain term used by reports.
        data["success"] = self.passed

        return data


# =============================================================
# Evaluation Summary
# =============================================================


@dataclass
class EvaluationSummary:

    run_name: str

    results: list[
        EvaluationResult
    ] = field(
        default_factory=list
    )

    metadata: dict = field(default_factory=dict)

    @property
    def total_cases(
        self,
    ) -> int:

        return len(
            self.results
        )

    @property
    def passed_cases(
        self,
    ) -> int:

        return sum(
            result.passed
            for result
            in self.results
        )

    @property
    def failed_cases(
        self,
    ) -> int:

        return (
            self.total_cases
            - self.passed_cases
        )

    @property
    def success_rate(
        self,
    ) -> float:

        if (
            self.total_cases
            == 0
        ):

            return 0.0

        return (
            self.passed_cases
            / self.total_cases
        )

    @property
    def total_tokens(
        self,
    ) -> int:

        return sum(
            result.total_tokens
            for result
            in self.results
        )

    @property
    def average_tokens(
        self,
    ) -> float:

        if (
            self.total_cases
            == 0
        ):

            return 0.0

        return (
            self.total_tokens
            / self.total_cases
        )

    @property
    def tokens_per_success(self) -> float:
        return self.total_tokens / self.passed_cases if self.passed_cases else 0.0

    @property
    def total_llm_calls(
        self,
    ) -> int:

        return sum(
            result.llm_calls
            for result
            in self.results
        )

    @property
    def average_llm_calls(
        self,
    ) -> float:

        if (
            self.total_cases
            == 0
        ):

            return 0.0

        return (
            self.total_llm_calls
            / self.total_cases
        )

    @property
    def total_duration_seconds(
        self,
    ) -> float:

        return sum(
            result.duration_seconds
            for result
            in self.results
        )

    @property
    def average_duration_seconds(
        self,
    ) -> float:

        if (
            self.total_cases
            == 0
        ):

            return 0.0

        return (
            self.total_duration_seconds
            / self.total_cases
        )

    @property
    def average_edit_revisions(
        self,
    ) -> float:

        if (
            self.total_cases
            == 0
        ):

            return 0.0

        return (
            sum(
                result.edit_revision
                for result
                in self.results
            )
            / self.total_cases
        )

    def vibe_metrics(self) -> dict:
        successes = [r for r in self.results if r.passed]
        recovery = [r for r in self.results if r.recovery_entered]
        first_pass_applicable = [r for r in self.results if r.category != "already_satisfied"]
        completed_validation = sum(r.validation_passes + r.validation_failures for r in self.results)
        total = len(self.results)
        successful = len(successes)

        def rate(count: int, denominator: int) -> float:
            return count / denominator if denominator else 0.0

        def average(values) -> float:
            values = list(values)
            return statistics.fmean(values) if values else 0.0

        def median(values):
            values = list(values)
            return statistics.median(values) if values else None

        known_costs = [r.cost_usd for r in self.results if r.cost_usd is not None]
        by_run: dict[int, list[bool]] = {}
        for result in self.results:
            by_run.setdefault(result.run_index, []).append(result.passed)
        run_success_rates = [statistics.fmean(values) for values in by_run.values()]
        return {
            "task_success_rate": self.success_rate,
            "task_success_rate_stddev": (
                statistics.pstdev(run_success_rates) if len(run_success_rates) > 1 else 0.0
            ),
            "first_pass_success_rate": rate(
                sum(r.first_pass_success for r in first_pass_applicable), len(first_pass_applicable)
            ),
            "false_completion_rate": rate(sum(r.false_completion for r in self.results), total),
            "recovery_success_rate": rate(sum(r.recovery_success for r in recovery), len(recovery)),
            "validation_pass_rate": rate(sum(r.validation_passes for r in self.results), completed_validation),
            "validation_inconclusive": sum(r.validation_inconclusive for r in self.results),
            "max_step_exhaustion_rate": rate(sum(r.max_steps_exhausted for r in self.results), total),
            "wrong_validation_target_rate": rate(sum(r.wrong_validation_target for r in self.results), total),
            "unauthorized_edit_count": sum(r.unauthorized_edit for r in self.results),
            "unauthorized_edit_rate": rate(sum(r.unauthorized_edit for r in self.results), total),
            "wrong_file_edit_count": sum(r.wrong_file_edit for r in self.results),
            "wrong_file_edit_rate": rate(sum(r.wrong_file_edit for r in self.results), total),
            "average_tool_calls": average(r.tool_call_count for r in self.results),
            "median_tool_calls": median(r.tool_call_count for r in self.results),
            "average_failed_tool_calls": average(r.failed_tool_call_count for r in self.results),
            "failed_tool_call_rate": rate(
                sum(r.failed_tool_call_count for r in self.results),
                sum(r.tool_call_count for r in self.results),
            ),
            "tool_calls_per_success": rate(sum(r.tool_call_count for r in self.results), successful),
            "average_steps": average(r.agent_steps for r in self.results),
            "median_steps": median(r.agent_steps for r in self.results),
            "average_llm_calls": average(r.llm_call_count for r in self.results),
            "llm_calls_per_success": rate(sum(r.llm_call_count for r in self.results), successful),
            "median_time_to_success": median([r.duration_seconds for r in successes]) if successes else None,
            "median_tokens_per_success": median([r.total_tokens for r in successes]) if successes else None,
            "median_cost_per_success_usd": median([r.cost_usd for r in successes if r.cost_usd is not None])
                if any(r.cost_usd is not None for r in successes) else None,
            "main_llm_calls_per_success": rate(sum(r.main_agent_llm_calls for r in self.results), successful),
            "control_llm_calls_per_success": rate(sum(r.total_control_llm_calls for r in self.results), successful),
            "median_time_to_first_edit": median(
                r.time_to_first_edit for r in self.results if r.time_to_first_edit is not None
            ),
            "average_inspections_before_first_edit": average(
                r.inspections_before_first_edit for r in self.results if r.inspections_before_first_edit is not None
            ),
            "repeated_tool_rate": rate(sum(r.repeated_action_count for r in self.results),
                                       sum(r.tool_call_count for r in self.results)),
            "rollback_rate": rate(sum(r.rollback_count > 0 for r in self.results), total),
            "average_tokens": average(r.total_tokens for r in self.results),
            "total_tokens": sum(r.total_tokens for r in self.results),
            "prompt_tokens": sum(r.prompt_tokens for r in self.results),
            "completion_tokens": sum(r.completion_tokens for r in self.results),
            "average_prompt_tokens": average(r.prompt_tokens for r in self.results),
            "average_completion_tokens": average(r.completion_tokens for r in self.results),
            "average_latency_seconds": average(r.duration_seconds for r in self.results),
            "median_latency_per_success_seconds": median(r.duration_seconds for r in successes),
            "cost_per_success_usd": (sum(known_costs) / successful
                                     if known_costs and successful else None),
            "executed_tool_turn_count": sum(r.executed_tool_turn_count for r in self.results),
            "ghost_step_count": sum(r.ghost_step_count for r in self.results),
            "ghost_step_rate": rate(
                sum(r.ghost_step_count for r in self.results),
                sum(r.agent_steps for r in self.results),
            ),
            "blocked_tool_selection_count": sum(
                r.blocked_tool_selection_count for r in self.results
            ),
            "productive_step_count": sum(r.productive_step_count for r in self.results),
            "text_only_step_count": sum(r.text_only_step_count for r in self.results),
            "average_executed_tool_turn_count": average(
                r.executed_tool_turn_count for r in self.results
            ),
            "average_ghost_step_count": average(r.ghost_step_count for r in self.results),
            "average_blocked_tool_selection_count": average(
                r.blocked_tool_selection_count for r in self.results
            ),
            "average_productive_step_count": average(
                r.productive_step_count for r in self.results
            ),
            "average_text_only_step_count": average(
                r.text_only_step_count for r in self.results
            ),
        }

    def metrics_by_category(self) -> dict:
        categories = sorted({result.category for result in self.results if result.category})
        return {
            category: EvaluationSummary(
                run_name=f"{self.run_name}:{category}",
                results=[result for result in self.results if result.category == category],
            ).vibe_metrics()
            for category in categories
        }

    def case_success_probabilities(self) -> dict[str, float]:
        by_case: dict[str, list[bool]] = {}
        for result in self.results:
            by_case.setdefault(result.case_id, []).append(result.passed)
        return {
            case_id: statistics.fmean(outcomes)
            for case_id, outcomes in sorted(by_case.items())
        }

    def to_dict(
        self,
    ) -> dict:

        return {
            "vibebench": self.vibe_metrics(),
            "metrics": self.vibe_metrics(),
            "metrics_by_category": self.metrics_by_category(),
            "case_success_probabilities": self.case_success_probabilities(),
            "metadata": self.metadata,
            "run_name": (
                self.run_name
            ),
            "total_cases": (
                self.total_cases
            ),
            "passed_cases": (
                self.passed_cases
            ),
            "failed_cases": (
                self.failed_cases
            ),
            "success_rate": (
                self.success_rate
            ),
            "total_tokens": (
                self.total_tokens
            ),
            "average_tokens": (
                self.average_tokens
            ),
            "tokens_per_success": self.tokens_per_success,
            "total_llm_calls": (
                self.total_llm_calls
            ),
            "average_llm_calls": (
                self.average_llm_calls
            ),
            "total_duration_seconds": (
                self.total_duration_seconds
            ),
            "average_duration_seconds": (
                self.average_duration_seconds
            ),
            "average_edit_revisions": (
                self.average_edit_revisions
            ),
            "results": [
                result.to_dict()
                for result
                in self.results
            ],
        }

    def save_json(
        self,
        path,
    ) -> None:

        target = (
            Path(
                path
            )
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


# =============================================================
# Version Comparison
# =============================================================


@dataclass(frozen=True)
class EvaluationComparison:

    baseline_run: str

    candidate_run: str

    baseline_success_rate: float

    candidate_success_rate: float

    success_rate_delta: float

    baseline_average_tokens: float

    candidate_average_tokens: float

    average_tokens_delta: float

    baseline_average_duration_seconds: float

    candidate_average_duration_seconds: float

    average_duration_delta_seconds: float

    baseline_average_edit_revisions: float

    candidate_average_edit_revisions: float

    average_edit_revisions_delta: float

    improved_cases: tuple[
        str,
        ...,
    ] = ()

    regressed_cases: tuple[
        str,
        ...,
    ] = ()

    unchanged_cases: tuple[
        str,
        ...,
    ] = ()
