from dataclasses import dataclass
from pathlib import Path

from ..agent.state import (
    AgentPlan,
    PlanStep,
    StepStatus,
)
from ..evaluation import (
    EvaluationCase,
    EvaluationCheck,
    EvaluationHarness,
    EvaluationResult,
    EvaluationSummary,
    compare_summaries,
)
from ..llm.types import (
    TokenUsage,
)


# =============================================================
# Fake Runtime State
# =============================================================


@dataclass
class FakeValidationState:

    edit_revision: int = 1

    has_edit: bool = True

    acceptance_passed: bool = True

    full_passed: bool = True


class FakeValidationPipeline:

    def __init__(
        self,
        state=None,
    ):

        self.state = (
            state
            or FakeValidationState()
        )


class FakeTokenMetrics:

    def __init__(
        self,
        *,
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        call_count=2,
    ):

        self.total = (
            TokenUsage(
                prompt_tokens=(
                    prompt_tokens
                ),
                completion_tokens=(
                    completion_tokens
                ),
                total_tokens=(
                    total_tokens
                ),
            )
        )

        self.call_count = (
            call_count
        )


# =============================================================
# Fake Agent
# =============================================================


class FakeAgent:

    def __init__(
        self,
        workspace: Path,
        *,
        success=True,
        output="done",
        total_tokens=120,
    ):

        self.workspace = (
            workspace
        )

        self.output = (
            output
        )

        self.validation_pipeline = (
            FakeValidationPipeline(
                FakeValidationState(
                    edit_revision=1,
                    has_edit=True,
                    acceptance_passed=(
                        success
                    ),
                    full_passed=(
                        success
                    ),
                )
            )
        )

        self.token_metrics = (
            FakeTokenMetrics(
                total_tokens=(
                    total_tokens
                )
            )
        )

        self.active_plan = (
            AgentPlan(
                goal="test",
                steps=[],
                completed_history=[
                    PlanStep(
                        id=1,
                        description="complete",
                        status=(
                            StepStatus.COMPLETED
                        ),
                    )
                ],
            )
        )

    def run(
        self,
        prompt,
    ):

        return (
            self.output
        )


# =============================================================
# Successful Case
# =============================================================


def test_successful_evaluation_case(
    tmp_path,
):

    target = (
        tmp_path
        / "app.py"
    )

    target.write_text(
        (
            "def add(a, b):\n"
            "    return a + b\n"
        ),
        encoding="utf-8",
    )

    def factory(
        case,
    ):

        return FakeAgent(
            tmp_path
        )

    harness = (
        EvaluationHarness(
            agent_factory=(
                factory
            )
        )
    )

    case = (
        EvaluationCase(
            case_id=(
                "addition"
            ),
            prompt=(
                "Fix add."
            ),
            checks=(
                EvaluationCheck(
                    kind=(
                        "file_contains"
                    ),
                    path=(
                        "app.py"
                    ),
                    expected=(
                        "return a + b"
                    ),
                ),
            ),
        )
    )

    result = (
        harness.run_case(
            case
        )
    )

    assert (
        result.passed
        is True
    )

    assert (
        result.completion_status
        == "ready"
    )

    assert (
        result.plan_completed
        is True
    )

    assert (
        result.total_tokens
        == 120
    )

    assert (
        result.llm_calls
        == 2
    )


# =============================================================
# Deterministic Check Failure
# =============================================================


def test_agent_claim_does_not_override_workspace_failure(
    tmp_path,
):

    (
        tmp_path
        / "app.py"
    ).write_text(
        "broken = True\n",
        encoding="utf-8",
    )

    def factory(
        case,
    ):

        return FakeAgent(
            tmp_path,
            success=True,
            output=(
                "Everything is fixed successfully."
            ),
        )

    harness = (
        EvaluationHarness(
            agent_factory=(
                factory
            )
        )
    )

    case = (
        EvaluationCase(
            case_id=(
                "real_state_wins"
            ),
            prompt=(
                "Fix app."
            ),
            checks=(
                EvaluationCheck(
                    kind=(
                        "file_contains"
                    ),
                    path=(
                        "app.py"
                    ),
                    expected=(
                        "fixed = True"
                    ),
                ),
            ),
        )
    )

    result = (
        harness.run_case(
            case
        )
    )

    assert (
        result.passed
        is False
    )

    assert (
        result.output
        == (
            "Everything is fixed successfully."
        )
    )

    assert (
        result.checks[
            0
        ].passed
        is False
    )


# =============================================================
# Missing Completion Evidence
# =============================================================


def test_missing_validation_evidence_fails_edit_case(
    tmp_path,
):

    def factory(
        case,
    ):

        return FakeAgent(
            tmp_path,
            success=False,
        )

    harness = (
        EvaluationHarness(
            agent_factory=(
                factory
            )
        )
    )

    case = (
        EvaluationCase(
            case_id=(
                "validation_required"
            ),
            prompt=(
                "Fix code."
            ),
        )
    )

    result = (
        harness.run_case(
            case
        )
    )

    assert (
        result.passed
        is False
    )

    assert (
        result.completion_status
        != "ready"
    )


# =============================================================
# Read-only Case
# =============================================================


def test_read_only_case_can_skip_completion_gate(
    tmp_path,
):

    def factory(
        case,
    ):

        return FakeAgent(
            tmp_path,
            success=False,
            output=(
                "The repository contains 5 tools."
            ),
        )

    harness = (
        EvaluationHarness(
            agent_factory=(
                factory
            )
        )
    )

    case = (
        EvaluationCase(
            case_id=(
                "read_only"
            ),
            prompt=(
                "How many tools exist?"
            ),
            checks=(
                EvaluationCheck(
                    kind=(
                        "output_contains"
                    ),
                    expected=(
                        "5 tools"
                    ),
                ),
            ),
            require_completion_ready=False,
        )
    )

    result = (
        harness.run_case(
            case
        )
    )

    assert (
        result.passed
        is True
    )


# =============================================================
# Token Budget
# =============================================================


def test_token_budget_can_fail_case(
    tmp_path,
):

    def factory(
        case,
    ):

        return FakeAgent(
            tmp_path,
            total_tokens=500,
        )

    harness = (
        EvaluationHarness(
            agent_factory=(
                factory
            )
        )
    )

    case = (
        EvaluationCase(
            case_id=(
                "token_budget"
            ),
            prompt=(
                "Fix code."
            ),
            max_total_tokens=200,
        )
    )

    result = (
        harness.run_case(
            case
        )
    )

    assert (
        result.passed
        is False
    )

    assert (
        result.total_tokens
        == 500
    )


# =============================================================
# Suite Summary
# =============================================================


def test_summary_metrics():

    summary = (
        EvaluationSummary(
            run_name=(
                "v1"
            ),
            results=[
                EvaluationResult(
                    case_id="a",
                    passed=True,
                    output="",
                    total_tokens=100,
                    llm_calls=2,
                    duration_seconds=1.0,
                    edit_revision=1,
                ),
                EvaluationResult(
                    case_id="b",
                    passed=False,
                    output="",
                    total_tokens=300,
                    llm_calls=4,
                    duration_seconds=3.0,
                    edit_revision=3,
                ),
            ],
        )
    )

    assert (
        summary.total_cases
        == 2
    )

    assert (
        summary.passed_cases
        == 1
    )

    assert (
        summary.success_rate
        == 0.5
    )

    assert (
        summary.average_tokens
        == 200
    )

    assert (
        summary.average_llm_calls
        == 3
    )

    assert (
        summary.average_duration_seconds
        == 2.0
    )

    assert (
        summary.average_edit_revisions
        == 2.0
    )


# =============================================================
# Version Comparison
# =============================================================


def test_compare_evaluation_runs():

    baseline = (
        EvaluationSummary(
            run_name=(
                "before"
            ),
            results=[
                EvaluationResult(
                    case_id="a",
                    passed=False,
                    output="",
                    total_tokens=200,
                ),
                EvaluationResult(
                    case_id="b",
                    passed=True,
                    output="",
                    total_tokens=300,
                ),
            ],
        )
    )

    candidate = (
        EvaluationSummary(
            run_name=(
                "after"
            ),
            results=[
                EvaluationResult(
                    case_id="a",
                    passed=True,
                    output="",
                    total_tokens=150,
                ),
                EvaluationResult(
                    case_id="b",
                    passed=False,
                    output="",
                    total_tokens=250,
                ),
            ],
        )
    )

    comparison = (
        compare_summaries(
            baseline,
            candidate,
        )
    )

    assert (
        comparison.improved_cases
        == (
            "a",
        )
    )

    assert (
        comparison.regressed_cases
        == (
            "b",
        )
    )

    assert (
        comparison.average_tokens_delta
        == -50
    )