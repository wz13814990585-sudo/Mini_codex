from types import SimpleNamespace

from ....agent.agent import MiniCodexAgent
from ....agent.routing import ExecutionMode
from ....agent.routing import policy_for
from ....agent.orchestration import ContextBuilder
from ....agent.routing import RoutingDecision, TaskIntent
from ....agent.task_state import AgentPhase, RuntimeEventType
from dataclasses import replace
from minicodex.tests.evidence_fixtures import record_evidence
from ....tools.registry import ToolRegistry


def make_agent(tmp_path):
    agent = MiniCodexAgent(llm=None, registry=ToolRegistry(), repo_map=None)
    agent.workspace = tmp_path
    agent.active_user_request = "Update app.py"
    agent.execution_route = RoutingDecision(
        intent=TaskIntent.MODIFY,
        mode=ExecutionMode.FAST,
        needs_plan=False,
        confidence=1.0,
        reason="fixture",
        target_paths=("app.py",),
    )
    agent.execution_policy = policy_for(ExecutionMode.FAST)
    agent.apply_runtime_event(RuntimeEventType.TASK_STARTED, intent=TaskIntent.MODIFY,
                              mode=ExecutionMode.FAST, user_request="Update app.py", target_paths=("app.py",))
    return agent


def test_acting_context_has_edit_hint_without_validation_noise(tmp_path):
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    agent = make_agent(tmp_path)
    agent.apply_runtime_event(RuntimeEventType.PHASE_CHANGED, phase=AgentPhase.ACTING)

    context = ContextBuilder().build(
        agent, current_plan_step=None, remaining_agent_steps=4
    )

    assert "Edit strategy: prefer patch_file" in context
    assert "Latest failure paths" not in context


def test_fixing_context_focuses_failure_paths(tmp_path):
    agent = make_agent(tmp_path)
    agent.apply_runtime_event(RuntimeEventType.PHASE_CHANGED, phase=AgentPhase.FIXING)
    ledger = agent.validation_pipeline.state
    evidence = record_evidence(ledger, "acceptance_passed", False)
    ledger.record(replace(evidence, details={"failure_paths": ["tests/test_app.py", "app.py"]}))

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
