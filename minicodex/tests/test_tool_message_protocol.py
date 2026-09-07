import copy
import json
from types import SimpleNamespace

import pytest

from ..agent.agent import MiniCodexAgent
from ..agent.loop import (
    acceptance_evidence_reminder,
    run_agent_loop,
)
from ..agent.message_protocol import (
    ToolMessageProtocolError,
    validate_tool_message_protocol,
)
from ..agent.plan_progress import PlanProgressReconciler
from ..agent.state import AgentPlan, PlanStep, StepStatus
from ..agent.tool_executor import PreparedToolCall, ToolExecution
from ..llm.types import LLMResponse, TokenUsage
from ..tools.registry import ToolRegistry
from ..tools.results import ToolResult


def tool_call(call_id, name, arguments=None):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments or {}),
        ),
    )


class FakeMessage:
    def __init__(self, *, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = list(tool_calls or [])

    def model_dump(self, exclude_none=True):
        payload = {"role": "assistant"}
        if self.content is not None:
            payload["content"] = self.content
        if self.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return payload


class ProtocolCheckingLLM:
    def __init__(self, first_message):
        self.responses = [
            first_message,
            FakeMessage(content="Done."),
        ]
        self.histories = []

    def chat(self, messages, tools=None):
        # This models the invariant checked immediately before a provider
        # request and proves that a second request is actually reachable.
        validate_tool_message_protocol(messages)
        self.histories.append(copy.deepcopy(messages))
        return LLMResponse(
            message=self.responses.pop(0),
            usage=TokenUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )


class ResultExecutor:
    def __init__(self, results=None):
        self.results = results or {}
        self.executed = []

    def prepare(self, tool_name, raw_arguments):
        return PreparedToolCall(
            tool_name=tool_name,
            arguments=json.loads(raw_arguments),
        )

    def execute_prepared(self, prepared):
        self.executed.append(prepared.tool_name)
        result = self.results.get(
            prepared.tool_name,
            ToolResult(success=True, summary="inspection result"),
        )
        return ToolExecution(
            tool_name=prepared.tool_name,
            arguments=prepared.arguments,
            result=result,
        )


def make_agent(first_message, *, no_progress=1, max_steps=2):
    llm = ProtocolCheckingLLM(first_message)
    agent = MiniCodexAgent(
        llm=llm,
        registry=ToolRegistry(),
        planner=None,
        repo_map=None,
        max_steps=max_steps,
        status_interval_seconds=0,
        max_no_progress_steps=no_progress,
    )
    agent.tool_executor = ResultExecutor()
    return agent, llm


def conversation_after_first_response(llm):
    # The second provider call contains system + original user + first batch
    # + optional control guidance + dynamic turn context.
    history = llm.histories[1]
    start = next(
        index
        for index, message in enumerate(history)
        if message.get("role") == "assistant"
        and message.get("tool_calls")
    )
    return history[start:]


def assert_batch_order(messages, ids):
    roles = [message["role"] for message in messages[: len(ids) + 2]]
    assert roles[: len(ids) + 1] == ["assistant", *(["tool"] * len(ids))]
    observed = [
        message["tool_call_id"]
        for message in messages[1 : len(ids) + 1]
    ]
    assert observed == ids
    assert len(observed) == len(set(observed))
    validate_tool_message_protocol(messages)


def test_first_tool_no_progress_closes_remaining_before_recovery():
    calls = [
        tool_call("A", "search_code", {"query": "setInterval"}),
        tool_call("B", "search_code", {"query": "restartBtn"}),
    ]
    agent, llm = make_agent(FakeMessage(tool_calls=calls))

    run_agent_loop(agent, "Inspect game")

    history = conversation_after_first_response(llm)
    assert_batch_order(history, ["A", "B"])
    assert "inspection result" in history[1]["content"]
    assert "skipped" in history[2]["content"].lower()
    assert history[3]["role"] == "user"
    assert "no-progress recovery" in history[3]["content"].lower()
    assert len(llm.histories) == 2


def test_second_tool_no_progress_has_no_extra_skipped_response():
    calls = [
        tool_call("A", "search_code", {"query": "setInterval"}),
        tool_call("B", "search_code", {"query": "restartBtn"}),
    ]
    agent, llm = make_agent(
        FakeMessage(tool_calls=calls),
        no_progress=2,
    )

    run_agent_loop(agent, "Inspect game")

    history = conversation_after_first_response(llm)
    assert_batch_order(history, ["A", "B"])
    assert "inspection result" in history[2]["content"]
    assert "skipped" not in history[2]["content"].lower()
    assert history[3]["role"] == "user"


def test_no_progress_restriction_closes_batch_before_guidance():
    calls = [
        tool_call("A", "search_code", {"query": "a"}),
        tool_call("B", "search_code", {"query": "b"}),
    ]
    agent, llm = make_agent(FakeMessage(tool_calls=calls))
    agent.no_progress_policy.recovery_active = True

    run_agent_loop(agent, "Inspect game")

    history = conversation_after_first_response(llm)
    assert_batch_order(history, ["A", "B"])
    assert "blocked" in history[1]["content"].lower()
    assert "skipped" in history[2]["content"].lower()
    assert history[3]["role"] == "user"


def test_validation_transition_closes_batch_before_followup():
    calls = [
        tool_call("A", "validate_static_web", {"path": "game.html"}),
        tool_call("B", "git_status"),
    ]
    agent, llm = make_agent(
        FakeMessage(tool_calls=calls),
        no_progress=10,
    )
    agent.validation_pipeline.record_edit()
    agent.tool_executor = ResultExecutor(
        {
            "validate_static_web": ToolResult(
                success=True,
                summary="Static web validation passed",
                data={"outcome": "passed", "errors": []},
            )
        }
    )

    run_agent_loop(agent, "Build game.html")

    history = conversation_after_first_response(llm)
    assert_batch_order(history, ["A", "B"])
    assert "skipped" in history[2]["content"].lower()
    assert history[3]["role"] == "user"
    assert "full regression" in history[3]["content"].lower()


def test_progress_recovery_closes_batch_before_message():
    calls = [
        tool_call("A", "search_code", {"query": "a"}),
        tool_call("B", "search_code", {"query": "b"}),
    ]
    agent, llm = make_agent(
        FakeMessage(tool_calls=calls),
        no_progress=20,
    )
    agent.active_plan = AgentPlan(
        goal="change",
        steps=[PlanStep(id=1, description="Implement behavior")],
    )
    agent.progress.recent_actions = [
        "run_tests",
        "run_tests",
        "read_file",
        "search_code",
        "git_status",
    ]

    run_agent_loop(agent, "Change behavior")

    history = conversation_after_first_response(llm)
    assert_batch_order(history, ["A", "B"])
    assert history[3]["role"] == "user"
    assert "recovery" in history[3]["content"].lower()


def test_protocol_validator_accepts_closed_batch():
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "A"}, {"id": "B"}]},
        {"role": "tool", "tool_call_id": "A", "content": "a"},
        {"role": "tool", "tool_call_id": "B", "content": "b"},
        {"role": "user", "content": "continue"},
    ]

    assert validate_tool_message_protocol(messages) is True


def test_protocol_validator_rejects_interleaved_user_message():
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "A"}, {"id": "B"}]},
        {"role": "tool", "tool_call_id": "A", "content": "a"},
        {"role": "user", "content": "recover"},
        {"role": "tool", "tool_call_id": "B", "content": "b"},
    ]

    with pytest.raises(ToolMessageProtocolError, match="interleaves"):
        validate_tool_message_protocol(messages)


def test_protocol_validator_rejects_duplicate_ids_and_responses():
    with pytest.raises(ToolMessageProtocolError, match="duplicate"):
        validate_tool_message_protocol(
            [
                {
                    "role": "assistant",
                    "tool_calls": [{"id": "A"}, {"id": "A"}],
                }
            ]
        )

    with pytest.raises(ToolMessageProtocolError, match="more than once"):
        validate_tool_message_protocol(
            [
                {
                    "role": "assistant",
                    "tool_calls": [{"id": "A"}, {"id": "B"}],
                },
                {"role": "tool", "tool_call_id": "A", "content": "a"},
                {"role": "tool", "tool_call_id": "A", "content": "again"},
            ]
        )


def test_stuck_reconciles_machine_criteria_before_generic_recovery(tmp_path):
    (tmp_path / "game.html").write_text("restartBtn", encoding="utf-8")
    calls = [
        tool_call("A", "search_code", {"query": "restartBtn"}),
        tool_call("B", "git_status"),
    ]
    agent, llm = make_agent(FakeMessage(tool_calls=calls))
    agent.plan_progress_reconciler = PlanProgressReconciler(tmp_path)
    agent.active_plan = AgentPlan(
        goal="game",
        steps=[
            PlanStep(
                id=1,
                description="Add restart",
                acceptance_criteria=[
                    {
                        "type": "contains_text",
                        "path": "game.html",
                        "text": "restartBtn",
                    }
                ],
            )
        ],
    )

    run_agent_loop(agent, "Build game")

    history = conversation_after_first_response(llm)
    assert_batch_order(history, ["A", "B"])
    assert agent.active_plan.is_completed() is True
    assert all(
        "deterministic no-progress recovery" not in str(message.get("content", "")).lower()
        for message in history
    )


def test_semantic_step_is_not_completed_from_search_results():
    calls = [
        tool_call("A", "search_code", {"query": "setInterval"}),
        tool_call("B", "search_code", {"query": "restartBtn"}),
    ]
    agent, llm = make_agent(FakeMessage(tool_calls=calls))
    step = PlanStep(
        id=1,
        description=(
            "Add falling, movement, rotation, locking, clearing, scoring, "
            "game over and restart"
        ),
    )
    agent.active_plan = AgentPlan(goal="Tetris", steps=[step])

    run_agent_loop(agent, "Build Tetris")

    history = conversation_after_first_response(llm)
    assert step.status == StepStatus.IN_PROGRESS
    assert agent.active_plan.is_completed() is False
    assert any(
        "deterministic no-progress recovery" in str(message.get("content", "")).lower()
        for message in history
    )


def test_html_acceptance_reminder_uses_static_web_validator():
    agent = SimpleNamespace(
        registry=SimpleNamespace(_tools={"validate_static_web": object()}),
        git_awareness=SimpleNamespace(
            task_state=lambda: SimpleNamespace(
                agent_touched_files=("try_code/index.html",)
            )
        ),
        active_plan=None,
        active_user_request="Build a game",
    )

    reminder = acceptance_evidence_reminder(agent)

    assert "validate_static_web" in reminder
    assert "try_code/index.html" in reminder
    assert "run_tests" not in reminder

