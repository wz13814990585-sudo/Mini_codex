from ..agent.agent import MiniCodexAgent
from ..agent.completion import CompletionStatus
from ..agent.loop import evaluate_completion
from ..agent.loop import run_agent_loop
from ..agent.plan_progress import PlanProgressReconciler
from ..agent.state import AgentPlan, PlanStep
from ..tools.registry import ToolRegistry
from ..tools.write_file import WriteFileTool
from ..llm.types import LLMResponse, TokenUsage
from types import SimpleNamespace
import json


def criterion_step(step_id, text):
    return PlanStep(
        id=step_id,
        description=f"Require {text}",
        acceptance_criteria=[
            {"type": "file_exists", "path": "game.html"},
            {
                "type": "contains_text",
                "path": "game.html",
                "text": text,
            },
        ],
    )


def test_plan_step_payload_supports_criteria_and_legacy_string():
    legacy = PlanStep.from_payload(
        step_id=1,
        payload="Inspect repository",
    )
    structured = PlanStep.from_payload(
        step_id=2,
        payload={
            "description": "Create game",
            "acceptance_criteria": [
                {
                    "type": "file_exists",
                    "path": "game.html",
                }
            ],
        },
    )

    assert legacy.acceptance_criteria == []
    assert structured.acceptance_criteria[0]["type"] == "file_exists"


def test_satisfied_and_unsatisfied_step_evaluation(tmp_path):
    (tmp_path / "game.html").write_text(
        "<html>data-row</html>",
        encoding="utf-8",
    )
    reconciler = PlanProgressReconciler(tmp_path)

    satisfied = reconciler.evaluate_step(
        criterion_step(1, "data-row")
    )
    unsatisfied = reconciler.evaluate_step(
        criterion_step(2, "data-col")
    )

    assert satisfied.machine_checkable is True
    assert satisfied.satisfied is True
    assert unsatisfied.machine_checkable is True
    assert unsatisfied.satisfied is False


def test_semantic_step_is_left_to_llm(tmp_path):
    step = PlanStep(
        id=1,
        description="Make the UI delightful",
    )

    result = PlanProgressReconciler(tmp_path).evaluate_step(step)

    assert result.machine_checkable is False
    assert result.satisfied is False


def test_one_large_html_edit_reconciles_multiple_steps(tmp_path):
    (tmp_path / "game.html").write_text(
        "<html><style></style><script></script>"
        "data-row data-col findPath restartBtn</html>",
        encoding="utf-8",
    )
    registry = ToolRegistry()
    agent = MiniCodexAgent(
        llm=None,
        registry=registry,
        planner=None,
        repo_map=None,
        status_interval_seconds=0,
    )
    agent.workspace = tmp_path
    agent.plan_progress_reconciler = PlanProgressReconciler(tmp_path)
    agent.active_plan = AgentPlan(
        goal="Lianliankan",
        steps=[
            criterion_step(1, "data-row"),
            criterion_step(2, "data-col"),
            criterion_step(3, "findPath"),
            criterion_step(4, "restartBtn"),
        ],
    )

    result = agent.reconcile_plan_progress()

    assert [item["step_id"] for item in result["completed"]] == [
        1, 2, 3, 4
    ]
    assert agent.active_plan.is_completed() is True


def test_local_step_completion_does_not_bypass_global_gate(tmp_path):
    registry = ToolRegistry()
    agent = MiniCodexAgent(
        llm=None,
        registry=registry,
        planner=None,
        repo_map=None,
        status_interval_seconds=0,
    )
    agent.active_plan = AgentPlan(
        goal="game",
        steps=[PlanStep(id=1, description="Create skeleton")],
    )
    agent.validation_pipeline.record_edit()

    completed = agent.complete_plan_step()
    completion = evaluate_completion(agent)

    assert completed["completed"] is True
    assert agent.active_plan.is_completed() is True
    assert completion.status == CompletionStatus.NEEDS_ACCEPTANCE
    assert completion.can_complete is False

    agent.validation_pipeline.state.acceptance_passed = True
    still_blocked = evaluate_completion(agent)
    assert still_blocked.status == CompletionStatus.NEEDS_FULL_VALIDATION

    agent.validation_pipeline.state.full_passed = True
    ready = evaluate_completion(agent)
    assert ready.status == CompletionStatus.READY
    assert ready.can_complete is True


def test_large_write_advances_machine_checkable_plan_in_loop(tmp_path):
    html = (
        "<html><style></style><body><script></script>"
        "data-row data-col findPath restartBtn</body></html>"
    )
    tool_call = SimpleNamespace(
        id="write-1",
        function=SimpleNamespace(
            name="write_file",
            arguments=json.dumps(
                {
                    "path": "game.html",
                    "content": html,
                }
            ),
        ),
    )
    message = SimpleNamespace(
        content=None,
        tool_calls=[tool_call],
        model_dump=lambda exclude_none=True: {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "write-1",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": tool_call.function.arguments,
                    },
                }
            ],
        },
    )

    class OneResponseLLM:
        def chat(self, messages, tools=None):
            return LLMResponse(
                message=message,
                usage=TokenUsage(
                    prompt_tokens=10,
                    completion_tokens=10,
                    total_tokens=20,
                ),
            )

    registry = ToolRegistry()
    registry.register(WriteFileTool(tmp_path))
    agent = MiniCodexAgent(
        llm=OneResponseLLM(),
        registry=registry,
        planner=None,
        repo_map=None,
        max_steps=1,
        status_interval_seconds=0,
    )
    agent.active_plan = AgentPlan(
        goal="Lianliankan",
        steps=[
            criterion_step(1, "data-row"),
            criterion_step(2, "data-col"),
            criterion_step(3, "findPath"),
            criterion_step(4, "restartBtn"),
        ],
    )

    run_agent_loop(agent, "Build game")

    assert agent.active_plan.is_completed() is True
    assert [
        step.id
        for step in agent.active_plan.completed_history
    ] == [1, 2, 3, 4]
    assert agent.validation_pipeline.state.acceptance_passed is False
