from ..agent.agent import MiniCodexAgent
from ..agent.planning import AgentPlan, PlanStep, StepStatus
from ..agent.routing import ExecutionMode, policy_for
from ..agent.task_state import (
    AgentPhase,
    RuntimeEvent,
    RuntimeEventType,
    TaskRuntime,
    TaskState,
    reduce_task_state,
)
from ..agent.validation import TaskOutcome, ValidationOutcome
from ..prompts.system import build_fast_system_prompt, build_system_prompt
from ..tools.filesystem import ReadFileTool
from ..tools.registry import SideEffectClass, ToolRegistry, ToolRisk
from ..tools.results import ToolErrorCode, ToolResult


def event(kind, **data):
    return RuntimeEvent.create(kind, **data)


def test_reducer_is_deterministic_and_edit_invalidates_evidence():
    started = reduce_task_state(
        TaskState(),
        event(
            RuntimeEventType.TASK_STARTED,
            run_id="run-1",
            mode=ExecutionMode.FAST,
            remaining_steps=8,
        ),
    )
    validated = reduce_task_state(
        started,
        event(
            RuntimeEventType.VALIDATION_OBSERVED,
            outcome=ValidationOutcome.PASSED,
            acceptance_passed=True,
            evidence_edit_revision=0,
        ),
    )
    edited_a = reduce_task_state(
        validated, event(RuntimeEventType.EDIT_APPLIED, edit_revision=1)
    )
    edited_b = reduce_task_state(
        validated, event(RuntimeEventType.EDIT_APPLIED, edit_revision=1)
    )

    assert edited_a == edited_b
    assert edited_a.phase == AgentPhase.VALIDATING
    assert edited_a.acceptance_passed is False
    assert edited_a.active_evidence_edit_revision is None


def test_runtime_records_ordered_events_and_terminal_outcome():
    runtime = TaskRuntime()
    runtime.emit(
        RuntimeEventType.TASK_STARTED,
        run_id="run-2",
        mode=ExecutionMode.FAST,
        remaining_steps=2,
    )
    runtime.emit(
        RuntimeEventType.TASK_COMPLETED,
        outcome=TaskOutcome.ALREADY_SATISFIED,
    )

    assert [item.kind for item in runtime.events] == [
        RuntimeEventType.TASK_STARTED,
        RuntimeEventType.TASK_COMPLETED,
    ]
    assert runtime.state.phase == AgentPhase.DONE
    assert runtime.can_continue() is False


def test_green_task_supersedes_unfinished_plan_bookkeeping():
    agent = MiniCodexAgent(llm=None, registry=ToolRegistry(), planner=None, repo_map=None)
    agent.execution_policy = policy_for(ExecutionMode.STANDARD)
    agent.active_plan = AgentPlan(
        goal="feature",
        steps=[
            PlanStep(id=1, description="Implementation exists"),
            PlanStep(id=2, description="Review the result"),
        ],
    )
    agent.validation_pipeline.record_edit()
    agent.validation_pipeline.state.acceptance_passed = True
    agent.validation_pipeline.state.targeted_passed = True
    agent.ensure_runtime_started("Implement feature")

    handled = agent.completion_handler.check_after_batch(agent)

    assert handled.finished is True
    assert agent.task_state.outcome == TaskOutcome.EDITED_AND_VALIDATED
    assert agent.active_plan.is_completed() is True
    assert all(step.status == StepStatus.SUPERSEDED for step in agent.active_plan.steps)
    assert agent.task_state.superseded_plan_steps == (1, 2)


def test_prompts_have_a_visible_growth_budget():
    assert len(build_system_prompt()) < 900
    assert len(build_fast_system_prompt()) < 1100
    assert "complete_plan_step" not in build_system_prompt()


def test_tool_results_expose_stable_error_codes():
    ambiguous = ToolResult(
        success=False,
        summary="matched multiple blocks",
        data={"failure_type": "ambiguous_match"},
        error="old_text matched three locations",
    )
    timeout = ToolResult(
        success=False,
        summary="timed out",
        data={"failure_type": "timeout"},
        error="deadline exceeded",
    )

    assert ambiguous.error_code == ToolErrorCode.AMBIGUOUS_MATCH
    assert timeout.error_code == ToolErrorCode.TIMEOUT
    assert "[ambiguous_match]" in ambiguous.to_llm_text()


def test_registry_exposes_backend_neutral_metadata(tmp_path):
    registry = ToolRegistry()
    registry.register(ReadFileTool(tmp_path))

    metadata = registry.metadata_for("read_file")

    assert metadata.read_only is True
    assert metadata.risk == ToolRisk.LOW
    assert metadata.side_effect == SideEffectClass.READ_ONLY
    assert metadata.backend == "local"
