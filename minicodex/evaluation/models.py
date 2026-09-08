"""Structured evaluation models for MiniCodex."""

from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from pathlib import Path
import json


# =============================================================
# Evaluation Check
# =============================================================


@dataclass(frozen=True)
class EvaluationCheck:

    kind: str

    expected: str | None = None

    path: str | None = None

    description: str | None = None


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

    duration_seconds: float = 0.0

    error: str | None = None

    tags: tuple[
        str,
        ...,
    ] = ()

    def to_dict(
        self,
    ) -> dict:

        data = asdict(
            self
        )

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

    def to_dict(
        self,
    ) -> dict:

        return {
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
