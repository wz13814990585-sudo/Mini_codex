from types import SimpleNamespace

from ..agent.action_controller import ActionController
from ..agent.agent import MiniCodexAgent
from ..agent.completion import CompletionStatus, TaskOutcome
from ..agent.completion_policy import TaskCompletionPolicy
from ..agent.execution_mode import ExecutionMode
from ..agent.execution_policy import policy_for
from ..agent.finalization import FinalizationController
from ..agent.state import AgentPlan, PlanStep
from ..agent.step_evidence import EvidenceStrength, StepEvidenceStore
from ..agent.task_router import TaskRouter
from ..agent.task_state import TaskState
from ..tools.registry import ToolRegistry
from ..tools.results import ToolResult


def state(edit=0, validation=0, completed=0, plan=0, rollback=0):
    return TaskState(
        edit_revision=edit,
        validation_revision=validation,
        completed_plan_steps=tuple(range(completed)),
        plan_revision=plan,
        rollback_revision=rollback,
    )


def test_action_controller_bounds_inspection_and_keeps_action_tools_open():
    controller = ActionController()
    policy = policy_for(ExecutionMode.FAST)
    controller.reset(state())

    for _ in range(policy.max_inspection_calls):
        assert controller.restriction_reason("read_file", {}, policy) is None
        assert controller.observe_action("read_file", state()) is False

    assert controller.restriction_reason("search_code", {}, policy)
    assert controller.action_required is True
    assert controller.restriction_reason("write_file", {}, policy) is None
    assert controller.restriction_reason("validate_static_web", {}, policy) is None
    assert controller.restriction_reason(
        "run_command", {"purpose": "acceptance"}, policy
    ) is None


def test_edit_and_validation_state_changes_reset_action_pressure():
    controller = ActionController()
    policy = policy_for(ExecutionMode.FAST)
    controller.reset(state())
    for _ in range(policy.max_inspection_calls):
        controller.observe_action("search_code", state())
    controller.update_pressure(policy)
    assert controller.action_required is True

    assert controller.observe_action("write_file", state(edit=1)) is True
    assert controller.action_required is False
    controller.observe_action("read_file", state(edit=1))
    assert controller.observe_action(
        "validate_static_web", state(edit=1, validation=1)
    ) is True
    assert controller.consecutive_no_state_change == 0


def test_repeated_observation_is_not_meaningful_progress():
    controller = ActionController()
    policy = policy_for(ExecutionMode.STANDARD)
    controller.reset(state())
    for _ in range(policy.max_no_progress_steps):
        assert controller.observe_action("search_code", state()) is False
    assert controller.update_pressure(policy) is True
    assert controller.action_required is True


def test_fast_tool_exposure_is_planless():
    class NamedTool:
        def __init__(self, name):
            self.name = name

        def to_schema(self):
            return {"type": "function", "function": {"name": self.name}}

    registry = ToolRegistry()
    for name in ("read_file", "write_file", "run_tests", "complete_plan_step", "replan"):
        registry.register(NamedTool(name))
    agent = MiniCodexAgent(llm=None, registry=registry, planner=None, repo_map=None)
    agent.execution_policy = policy_for(ExecutionMode.FAST)

    names = {schema["function"]["name"] for schema in agent.get_tool_schemas()}
    assert {"read_file", "write_file", "run_tests"} <= names
    assert "complete_plan_step" not in names
    assert "replan" not in names


def test_fast_is_planless_even_when_legacy_caller_requests_planning(tmp_path):
    class FinalLLM:
        def chat(self, messages, tools=None):
            from ..llm.types import LLMResponse, TokenUsage

            return LLMResponse(
                message=SimpleNamespace(content="BLOCKED: fixture stop", tool_calls=[]),
                usage=TokenUsage(),
            )

    planner = SimpleNamespace(
        create_plan=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("FAST must not invoke Planner")
        )
    )
    agent = MiniCodexAgent(
        llm=FinalLLM(),
        registry=ToolRegistry(),
        planner=planner,
        repo_map=None,
        status_interval_seconds=0,
    )
    agent.run("Create try_code/game.html", use_planning=True)
    assert agent.active_plan is None
    assert agent.execution_metrics.final_outcome == "blocked"


def test_router_uses_semantics_not_single_path_only():
    router = TaskRouter()
    assert router.route("Create try_code/game.html").mode == ExecutionMode.FAST
    assert router.route("Update README.md setup instructions").mode == ExecutionMode.FAST
    assert router.route(
        "Redesign the complete orchestration state machine in minicodex/agent/loop.py"
    ).mode == ExecutionMode.COMPLEX
    assert router.route("Improve account settings behavior").mode == ExecutionMode.STANDARD
    assert router.route("Refactor runtime concurrency handling").mode == ExecutionMode.COMPLEX


def completion_agent(mode, *, edit, acceptance, relevant=False, full=False, plan=True):
    policy = policy_for(mode)
    active_plan = None
    if policy.use_plan:
        step = PlanStep(id=1, description="Outcome exists")
        active_plan = AgentPlan(goal="goal", steps=[step])
        if plan:
            active_plan.start_current_step()
            active_plan.complete_current_step()
    state_obj = SimpleNamespace(
        edit_revision=int(edit),
        has_edit=edit,
        acceptance_passed=acceptance,
        targeted_passed=relevant,
        full_passed=full,
    )
    return SimpleNamespace(
        execution_policy=policy,
        validation_pipeline=SimpleNamespace(state=state_obj),
        active_plan=active_plan,
    )


def test_mode_specific_completion_and_already_satisfied():
    completion = TaskCompletionPolicy()
    fast_edit = completion.evaluate(
        completion_agent(ExecutionMode.FAST, edit=True, acceptance=True)
    )
    fast_existing = completion.evaluate(
        completion_agent(ExecutionMode.FAST, edit=False, acceptance=True)
    )
    standard = completion.evaluate(
        completion_agent(
            ExecutionMode.STANDARD,
            edit=True,
            acceptance=True,
            relevant=True,
        )
    )
    complex_missing = completion.evaluate(
        completion_agent(
            ExecutionMode.COMPLEX,
            edit=True,
            acceptance=True,
            relevant=True,
        )
    )
    complex_ready = completion.evaluate(
        completion_agent(
            ExecutionMode.COMPLEX,
            edit=True,
            acceptance=True,
            full=True,
        )
    )

    assert fast_edit.outcome == TaskOutcome.EDITED_AND_VALIDATED
    assert fast_existing.outcome == TaskOutcome.ALREADY_SATISFIED
    assert standard.status == CompletionStatus.READY
    assert complex_missing.status == CompletionStatus.NEEDS_FULL_VALIDATION
    assert complex_ready.status == CompletionStatus.READY


def test_standard_requires_completed_plan_even_with_green_evidence():
    completion = TaskCompletionPolicy()
    agent = completion_agent(
        ExecutionMode.STANDARD,
        edit=True,
        acceptance=True,
        relevant=True,
        plan=False,
    )
    decision = completion.evaluate(agent)
    assert decision.status == CompletionStatus.NOT_READY
    assert decision.outcome == TaskOutcome.INCOMPLETE


def test_semantic_evidence_strength_rules():
    store = StepEvidenceStore()
    ok = ToolResult(success=True, summary="ok", data={})
    observed = store.record(
        step_id=1,
        edit_revision=1,
        tool_name="read_file",
        arguments={"path": "app.py"},
        result=ok,
    )
    assert observed.strength == EvidenceStrength.OBSERVATION
    assert store.has_sufficient(step_id=1, edit_revision=1) is False

    store.record(
        step_id=1,
        edit_revision=1,
        tool_name="patch_file",
        arguments={"path": "app.py"},
        result=ok,
    )
    assert store.has_sufficient(step_id=1, edit_revision=1) is True

    validation_store = StepEvidenceStore()
    validation_store.record(
        step_id=2,
        edit_revision=1,
        tool_name="validate_static_web",
        arguments={"path": "game.html"},
        result=ToolResult(
            success=True,
            summary="passed",
            data={"outcome": "passed"},
        ),
    )
    assert validation_store.has_sufficient(step_id=2, edit_revision=1) is True


def test_finalization_still_blocks_only_reconnaissance():
    controller = FinalizationController()
    policy = policy_for(ExecutionMode.FAST)
    assert controller.enter_if_needed(2, policy) is True
    assert controller.restriction_reason("git_diff")
    assert controller.restriction_reason("validate_static_web") is None


def test_fast_standalone_scope_rejects_full_repository_regression():
    controller = ActionController()
    policy = policy_for(ExecutionMode.FAST)
    reason = controller.restriction_reason(
        "run_tests",
        {"path": ".", "purpose": "regression"},
        policy,
    )
    assert "not applicable" in reason
