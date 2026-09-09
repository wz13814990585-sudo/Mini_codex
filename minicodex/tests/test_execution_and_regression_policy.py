from types import SimpleNamespace

from ..agent.validation import CompletionGate, CompletionStatus
from ..agent.routing import ExecutionMode
from ..agent.routing import policy_for
from ..agent.orchestration.validation_orchestrator import (
    active_plan_incomplete,
    evaluate_completion,
)
from ..agent.validation import (
    RegressionPolicy,
    RegressionRequirement,
)


def test_mode_policies_are_centralized_and_proportional():
    fast = policy_for(ExecutionMode.FAST)
    standard = policy_for(ExecutionMode.STANDARD)
    complex_policy = policy_for(ExecutionMode.COMPLEX)

    assert fast.use_plan is False
    assert standard.use_plan is True
    assert standard.max_plan_steps <= 4
    assert complex_policy.use_plan is True
    assert fast.max_steps < standard.max_steps < complex_policy.max_steps
    assert fast.enable_replan is False
    assert complex_policy.enable_long_term_memory is True


def test_regression_policy_uses_change_scope_and_mode():
    policy = RegressionPolicy()

    assert policy.requirement_for(
        mode=ExecutionMode.FAST,
        changed_paths=("try_code/index.html",),
    ) == RegressionRequirement.NOT_APPLICABLE
    assert policy.requirement_for(
        mode=ExecutionMode.FAST,
        changed_paths=("README.md",),
    ) == RegressionRequirement.NOT_APPLICABLE
    assert policy.requirement_for(
        mode=ExecutionMode.STANDARD,
        changed_paths=("minicodex/agent/orchestration/loop.py",),
    ) == RegressionRequirement.RELEVANT_ONLY
    assert policy.requirement_for(
        mode=ExecutionMode.COMPLEX,
        changed_paths=("try_code/index.html",),
    ) == RegressionRequirement.REQUIRED


def test_fast_acceptance_is_ready_without_full_regression():
    decision = CompletionGate().evaluate(
        edit_revision=1,
        has_edit=True,
        acceptance_passed=True,
        full_validation_passed=False,
        regression_requirement=RegressionRequirement.NOT_APPLICABLE,
    )

    assert decision.status == CompletionStatus.READY


def test_standard_relevant_regression_and_complex_full_regression():
    gate = CompletionGate()
    standard = gate.evaluate(
        edit_revision=1,
        has_edit=True,
        acceptance_passed=True,
        relevant_validation_passed=True,
        full_validation_passed=False,
        regression_requirement=RegressionRequirement.RELEVANT_ONLY,
    )
    complex_missing = gate.evaluate(
        edit_revision=1,
        has_edit=True,
        acceptance_passed=True,
        relevant_validation_passed=True,
        full_validation_passed=False,
        regression_requirement=RegressionRequirement.REQUIRED,
    )

    assert standard.status == CompletionStatus.READY
    assert complex_missing.status == CompletionStatus.NEEDS_FULL_VALIDATION


def test_fast_does_not_use_stale_plan_as_completion_authority():
    agent = SimpleNamespace(
        execution_policy=policy_for(ExecutionMode.FAST),
        active_plan=SimpleNamespace(is_completed=lambda: False),
    )

    assert active_plan_incomplete(agent) is False


def test_evaluate_completion_defaults_to_complex_mode():
    state = SimpleNamespace(
        edit_revision=1,
        has_edit=True,
        acceptance_passed=True,
        targeted_passed=False,
        full_passed=False,
    )
    agent = SimpleNamespace(
        execution_policy=None,
        validation_pipeline=SimpleNamespace(state=state),
    )

    assert evaluate_completion(agent).status == CompletionStatus.NEEDS_FULL_VALIDATION
