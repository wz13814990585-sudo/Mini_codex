from types import SimpleNamespace

from ....agent.completion import CompletionStatus, TaskOutcome
from ....agent.completion_policy import TaskCompletionPolicy
from ....agent.execution_mode import ExecutionMode
from ....agent.execution_policy import policy_for
from ....agent.task_state import AgentPhase, TaskState
from ....agent.validation import ValidationPipeline


def policy_agent(mode):
    policy = policy_for(mode)
    pipeline = ValidationPipeline()
    pipeline.record_edit()
    state = TaskState(mode=mode, phase=AgentPhase.VALIDATING, edit_revision=1)
    return SimpleNamespace(
        validation_pipeline=pipeline,
        execution_policy=policy,
        current_regression_requirement=lambda: policy.regression_requirement,
        active_plan=SimpleNamespace(is_completed=lambda: True),
        task_state=state,
    )


def test_fast_acceptance_pass_can_transition_ready_to_done():
    agent = policy_agent(ExecutionMode.FAST)
    agent.validation_pipeline.state.acceptance_passed = True

    decision = TaskCompletionPolicy().evaluate(agent)
    agent.task_state.finish(decision.outcome)

    assert decision.status == CompletionStatus.READY
    assert agent.task_state.phase == AgentPhase.DONE
    assert decision.outcome == TaskOutcome.EDITED_AND_VALIDATED


def test_standard_acceptance_pass_stays_validating_until_relevant_regression():
    agent = policy_agent(ExecutionMode.STANDARD)
    agent.validation_pipeline.state.acceptance_passed = True

    missing = TaskCompletionPolicy().evaluate(agent)

    assert missing.status == CompletionStatus.NEEDS_RELEVANT_VALIDATION
    assert agent.task_state.phase == AgentPhase.VALIDATING

    agent.validation_pipeline.state.targeted_passed = True
    ready = TaskCompletionPolicy().evaluate(agent)
    assert ready.status == CompletionStatus.READY


def test_complex_acceptance_pass_stays_validating_until_full_regression():
    agent = policy_agent(ExecutionMode.COMPLEX)
    agent.validation_pipeline.state.acceptance_passed = True

    missing = TaskCompletionPolicy().evaluate(agent)

    assert missing.status == CompletionStatus.NEEDS_FULL_VALIDATION
    assert agent.task_state.phase == AgentPhase.VALIDATING

    agent.validation_pipeline.state.full_passed = True
    ready = TaskCompletionPolicy().evaluate(agent)
    assert ready.status == CompletionStatus.READY
