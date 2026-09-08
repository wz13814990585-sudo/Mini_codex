from types import SimpleNamespace

from ....agent.agent import MiniCodexAgent
from ....agent.execution_mode import ExecutionMode
from ....agent.execution_policy import policy_for
from ....agent.orchestration import ContextBuilder
from ....agent.routing import TaskIntent, TaskRoute
from ....agent.task_state import AgentPhase
from ....tools.registry import ToolRegistry


def make_agent(tmp_path):
    agent = MiniCodexAgent(llm=None, registry=ToolRegistry(), repo_map=None)
    agent.workspace = tmp_path
    agent.active_user_request = "Update app.py"
    agent.execution_route = TaskRoute(
        intent=TaskIntent.MODIFY,
        mode=ExecutionMode.FAST,
        reason="fixture",
        target_paths=("app.py",),
    )
    agent.execution_policy = policy_for(ExecutionMode.FAST)
    agent.task_state.intent = TaskIntent.MODIFY
    agent.task_state.mode = ExecutionMode.FAST
    agent.task_state.user_request = "Update app.py"
    agent.task_state.target_paths = ("app.py",)
    return agent


def test_acting_context_has_edit_hint_without_validation_noise(tmp_path):
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    agent = make_agent(tmp_path)
    agent.task_state.phase = AgentPhase.ACTING

    context = ContextBuilder().build(
        agent, current_plan_step=None, remaining_agent_steps=4
    )

    assert "Edit strategy: prefer patch_file" in context
    assert "Latest failure paths" not in context


def test_fixing_context_focuses_failure_paths(tmp_path):
    agent = make_agent(tmp_path)
    agent.task_state.phase = AgentPhase.FIXING
    agent.validation_pipeline.state.latest_evidence = SimpleNamespace(
        outcome=SimpleNamespace(value="failed"),
        details={"failure_paths": ["tests/test_app.py", "app.py"]},
    )

    context = ContextBuilder().build(
        agent, current_plan_step=None, remaining_agent_steps=3
    )

    assert "tests/test_app.py, app.py" in context
    assert "Recover locally" in context


def test_context_builder_keeps_attached_long_term_memory_advisory(tmp_path):
    agent = make_agent(tmp_path)
    agent._retrieved_long_term_memory = ["prior"]
    agent.long_term_memory_store = SimpleNamespace(
        render_retrieved=lambda records: "Previous attempt needed a narrower patch."
    )

    context = ContextBuilder().build(
        agent, current_plan_step=None, remaining_agent_steps=3
    )

    assert "Advisory prior-task memory" in context
    assert "narrower patch" in context
