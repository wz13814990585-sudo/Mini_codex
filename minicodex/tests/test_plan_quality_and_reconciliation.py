import json
from types import SimpleNamespace

import pytest

from ..agent.agent import MiniCodexAgent
from ..agent.routing import ExecutionMode
from ..agent.routing import policy_for
from ..agent.planning import PlanQualityValidator
from ..agent.planning import Planner
from ..agent.planning import AgentPlan, PlanStep
from ..agent.planning import PlanProgressReconciler
from ..agent.orchestration.loop import run_agent_loop
from ..llm.types import LLMResponse, TokenUsage
from ..tools.registry import ToolRegistry
from ..tools.filesystem import ReadFileTool
from ..tools.results import ToolResult


def response(content):
    return LLMResponse(
        message=SimpleNamespace(content=content, tool_calls=[]),
        usage=TokenUsage(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )


class SequenceLLM:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        return response(self.contents.pop(0))


def test_broad_plan_is_regenerated_once():
    broad = """{
      "goal": "game",
      "steps": [{
        "description": "Add movement, rotation, locking, clearing, scoring, game over and restart",
        "acceptance_criteria": []
      }]
    }"""
    improved = """{
      "goal": "game",
      "steps": [
        {"description": "Game board exists", "acceptance_criteria": [{"type": "file_exists", "path": "game.html"}]},
        {"description": "Core interaction works", "acceptance_criteria": []}
      ]
    }"""
    llm = SequenceLLM([broad, improved])

    plan = Planner(llm).create_plan("Build game")

    assert llm.calls == 2
    assert len(plan.steps) == 2


def test_process_only_plan_uses_fallback_after_one_regeneration():
    process_plan = """{
      "goal": "inspect",
      "steps": [
        {"description": "Inspect source", "acceptance_criteria": []},
        {"description": "Review current state", "acceptance_criteria": []}
      ]
    }"""
    llm = SequenceLLM([process_plan, process_plan])

    plan = Planner(llm).create_plan("Fix behavior")

    assert llm.calls == 2
    assert len(plan.steps) == 2
    assert "implementation outcome" in plan.steps[0].description.lower()


def test_semantic_completion_requires_fresh_current_revision_evidence():
    agent = MiniCodexAgent(
        llm=None,
        registry=ToolRegistry(),
        planner=None,
        repo_map=None,
    )
    agent.execution_policy = policy_for(ExecutionMode.STANDARD)
    step = PlanStep(id=1, description="Interaction behaves correctly")
    agent.active_plan = AgentPlan(goal="feature", steps=[step])

    rejected = agent.complete_plan_step()

    assert rejected["completed"] is False
    assert rejected["failure_type"] == (
        "semantic_step_completion_without_fresh_evidence"
    )

    agent.step_evidence.record(
        step_id=1,
        edit_revision=0,
        tool_name="read_file",
        arguments={"path": "app.py"},
        result=ToolResult(success=True, summary="Current source inspected"),
    )

    assert agent.complete_plan_step()["completed"] is False

    agent.step_evidence.record(
        step_id=1,
        edit_revision=0,
        tool_name="write_file",
        arguments={"path": "app.py"},
        result=ToolResult(success=True, summary="Implementation written"),
    )

    assert agent.complete_plan_step()["completed"] is True


def test_semantic_completion_rejects_evidence_from_old_revision():
    agent = MiniCodexAgent(
        llm=None,
        registry=ToolRegistry(),
        planner=None,
        repo_map=None,
    )
    agent.execution_policy = policy_for(ExecutionMode.COMPLEX)
    agent.active_plan = AgentPlan(
        goal="feature",
        steps=[PlanStep(id=1, description="Behavior works")],
    )
    agent.step_evidence.record(
        step_id=1,
        edit_revision=0,
        tool_name="read_file",
        arguments={"path": "app.py"},
        result=ToolResult(success=True, summary="Old source"),
    )
    agent.validation_pipeline.record_edit()

    result = agent.complete_plan_step()

    assert result["completed"] is False
    assert result["failure_type"] == (
        "semantic_step_completion_without_fresh_evidence"
    )


def test_plan_quality_marks_broad_semantic_step_conservatively():
    step = PlanStep(
        id=3,
        description=(
            "Add falling, movement, acceleration, rotation, locking, "
            "clearing, scoring and restart"
        ),
    )

    report = PlanQualityValidator().validate([step])

    assert report.should_regenerate is True
    assert step.requires_semantic_completion is True
    assert step.id == 3  # The validator annotates; it does not split text.


def test_initial_reconciliation_skips_already_satisfied_step(tmp_path):
    (tmp_path / "ready.txt").write_text("ready", encoding="utf-8")
    plan = AgentPlan(
        goal="existing work",
        steps=[
            PlanStep(
                id=1,
                description="Ready artifact exists",
                acceptance_criteria=[
                    {"type": "file_exists", "path": "ready.txt"}
                ],
            )
        ],
    )
    planner = SimpleNamespace(create_plan=lambda *args, **kwargs: plan)
    llm = SequenceLLM(['{"unused": true}'])
    # The execution loop only needs a final textual response here.
    llm.contents = []

    def final_chat(messages, tools=None):
        llm.calls += 1
        return LLMResponse(
            message=SimpleNamespace(content="Done.", tool_calls=[]),
            usage=TokenUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )

    llm.chat = final_chat
    agent = MiniCodexAgent(
        llm=llm,
        registry=ToolRegistry(),
        planner=planner,
        repo_map=None,
        max_steps=2,
        status_interval_seconds=0,
    )
    agent.plan_progress_reconciler = PlanProgressReconciler(tmp_path)

    agent.run(
        "Improve existing behavior",
        policy=policy_for(ExecutionMode.STANDARD),
    )

    assert plan.is_completed() is True
    assert [step.id for step in plan.completed_history] == [1]


def test_final_reconciliation_can_finish_stale_plan_bookkeeping(tmp_path):
    (tmp_path / "ready.txt").write_text("ready", encoding="utf-8")
    call = SimpleNamespace(
        id="read",
        function=SimpleNamespace(
            name="read_file",
            arguments=json.dumps({"path": "ready.txt"}),
        ),
    )

    class ToolMessage:
        content = None
        tool_calls = [call]

        @staticmethod
        def model_dump(exclude_none=True):
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "read",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": call.function.arguments,
                        },
                    }
                ],
            }

    llm = SimpleNamespace(
        chat=lambda messages, tools=None: LLMResponse(
            message=ToolMessage(),
            usage=TokenUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )
    )
    registry = ToolRegistry()
    registry.register(ReadFileTool(tmp_path))
    agent = MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=None,
        repo_map=None,
        max_steps=1,
        status_interval_seconds=0,
    )
    agent.execution_policy = policy_for(ExecutionMode.STANDARD)
    agent.task_max_steps = 1
    agent.plan_progress_reconciler = PlanProgressReconciler(tmp_path)
    agent.active_plan = AgentPlan(
        goal="ready",
        steps=[
            PlanStep(
                id=1,
                description="Artifact exists",
                acceptance_criteria=[
                    {"type": "file_exists", "path": "ready.txt"}
                ],
            )
        ],
    )
    agent.validation_pipeline.record_edit()
    agent.validation_pipeline.state.acceptance_passed = True
    agent.validation_pipeline.state.targeted_passed = True

    result = run_agent_loop(agent, "Finish existing work")

    assert agent.active_plan.is_completed() is True
    assert agent.execution_metrics.final_outcome == "edited_and_validated"
    assert "Outcome:" not in result
