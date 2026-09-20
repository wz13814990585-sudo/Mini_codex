from minicodex.tests.evidence_fixtures import record_evidence
from types import SimpleNamespace

from ....agent.validation import CompletionStatus, TaskOutcome
from ....agent.validation import TaskCompletionPolicy
from ....agent.routing import ExecutionMode
from ....agent.routing import policy_for
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
    record_evidence(agent.validation_pipeline.state, "acceptance_passed", True)

    decision = TaskCompletionPolicy().evaluate(agent)
    from minicodex.agent.task_state import TaskRuntime, RuntimeEventType
    runtime = TaskRuntime(agent.task_state)
    runtime.emit(RuntimeEventType.VALIDATION_OBSERVED, acceptance_passed=True)
    agent.task_state = runtime.emit(RuntimeEventType.TASK_COMPLETED, outcome=decision.outcome)

    assert decision.status == CompletionStatus.READY
    assert agent.task_state.phase == AgentPhase.DONE
    assert decision.outcome == TaskOutcome.EDITED_AND_VALIDATED


def test_standard_acceptance_is_ready_when_plan_has_no_regression_check():
    agent = policy_agent(ExecutionMode.STANDARD)
    record_evidence(agent.validation_pipeline.state, "acceptance_passed", True)

    missing = TaskCompletionPolicy().evaluate(agent)

    assert missing.status == CompletionStatus.READY
    assert agent.task_state.phase == AgentPhase.VALIDATING

    record_evidence(agent.validation_pipeline.state, "targeted_passed", True)
    ready = TaskCompletionPolicy().evaluate(agent)
    assert ready.status == CompletionStatus.READY


def test_complex_acceptance_is_ready_when_plan_has_no_regression_check():
    agent = policy_agent(ExecutionMode.COMPLEX)
    record_evidence(agent.validation_pipeline.state, "acceptance_passed", True)

    missing = TaskCompletionPolicy().evaluate(agent)

    assert missing.status == CompletionStatus.READY
    assert agent.task_state.phase == AgentPhase.VALIDATING

    record_evidence(agent.validation_pipeline.state, "full_passed", True)
    ready = TaskCompletionPolicy().evaluate(agent)
    assert ready.status == CompletionStatus.READY
