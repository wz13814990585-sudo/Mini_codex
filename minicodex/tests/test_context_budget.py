from ..agent.context_budget import (
    ContextBudget,
    ContextPressure,
)


def test_context_budget_initial_state():

    budget = ContextBudget(
        max_context_tokens=1000
    )

    assert (
        budget.last_prompt_tokens
        == 0
    )

    assert (
        budget.usage_ratio
        == 0.0
    )

    assert (
        budget.pressure
        == ContextPressure.NORMAL
    )


def test_context_budget_normal_pressure():

    budget = ContextBudget(
        max_context_tokens=1000,
        warning_ratio=0.60,
        critical_ratio=0.80,
    )

    budget.observe(
        500
    )

    assert (
        budget.last_prompt_tokens
        == 500
    )

    assert (
        budget.usage_ratio
        == 0.5
    )

    assert (
        budget.pressure
        == ContextPressure.NORMAL
    )


def test_context_budget_warning_pressure():

    budget = ContextBudget(
        max_context_tokens=1000,
        warning_ratio=0.60,
        critical_ratio=0.80,
    )

    budget.observe(
        600
    )

    assert (
        budget.pressure
        == ContextPressure.WARNING
    )


def test_context_budget_critical_pressure():

    budget = ContextBudget(
        max_context_tokens=1000,
        warning_ratio=0.60,
        critical_ratio=0.80,
    )

    budget.observe(
        800
    )

    assert (
        budget.pressure
        == ContextPressure.CRITICAL
    )


def test_context_budget_reset():

    budget = ContextBudget(
        max_context_tokens=1000
    )

    budget.observe(
        900
    )

    assert (
        budget.last_prompt_tokens
        == 900
    )

    budget.reset()

    assert (
        budget.last_prompt_tokens
        == 0
    )

    assert (
        budget.pressure
        == ContextPressure.NORMAL
    )


def test_context_budget_negative_observation_is_clamped():

    budget = ContextBudget(
        max_context_tokens=1000
    )

    budget.observe(
        -100
    )

    assert (
        budget.last_prompt_tokens
        == 0
    )


def test_context_budget_zero_max_tokens_is_safe():

    budget = ContextBudget(
        max_context_tokens=0
    )

    budget.observe(
        100
    )

    assert (
        budget.usage_ratio
        == 0.0
    )

    assert (
        budget.pressure
        == ContextPressure.NORMAL
    )

from ..agent.context import (
    compact_messages_for_pressure,
)
from ..agent.context_budget import (
    ContextPressure,
)


def build_messages():

    large_result_1 = (
        "A" * 1200
    )

    large_result_2 = (
        "B" * 1200
    )

    large_result_3 = (
        "C" * 1200
    )

    return [
        {
            "role": "user",
            "content": "Fix the project.",
        },

        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": (
                            '{"path": "a.py"}'
                        ),
                    },
                }
            ],
        },

        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": large_result_1,
        },

        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call-2",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": (
                            '{"path": "b.py"}'
                        ),
                    },
                }
            ],
        },

        {
            "role": "tool",
            "tool_call_id": "call-2",
            "content": large_result_2,
        },

        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call-3",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": (
                            '{"path": "c.py"}'
                        ),
                    },
                }
            ],
        },

        {
            "role": "tool",
            "tool_call_id": "call-3",
            "content": large_result_3,
        },
    ]


def test_normal_pressure_keeps_two_recent_rounds():

    messages = build_messages()

    compact_messages_for_pressure(
        messages,
        ContextPressure.NORMAL,
    )

    # Oldest tool round should be compacted.
    assert (
        messages[2]["content"]
        != "A" * 1200
    )

    # Two most recent tool rounds remain full.
    assert (
        messages[4]["content"]
        == "B" * 1200
    )

    assert (
        messages[6]["content"]
        == "C" * 1200
    )


def test_warning_pressure_keeps_one_recent_round():

    messages = build_messages()

    compact_messages_for_pressure(
        messages,
        ContextPressure.WARNING,
    )

    assert (
        messages[2]["content"]
        != "A" * 1200
    )

    assert (
        messages[4]["content"]
        != "B" * 1200
    )

    # Most recent round remains full.
    assert (
        messages[6]["content"]
        == "C" * 1200
    )


def test_critical_pressure_keeps_one_recent_round():

    messages = build_messages()

    compact_messages_for_pressure(
        messages,
        ContextPressure.CRITICAL,
    )

    assert (
        messages[2]["content"]
        != "A" * 1200
    )

    assert (
        messages[4]["content"]
        != "B" * 1200
    )

    assert (
        messages[6]["content"]
        == "C" * 1200
    )

from ..agent.agent import MiniCodexAgent
from ..llm.types import (
    LLMResponse,
    TokenUsage,
)
from ..tools.registry import ToolRegistry


class FakeMessage:

    def __init__(
        self,
        content="Done.",
    ):
        self.content = content
        self.tool_calls = []

    def model_dump(
        self,
        exclude_none=True,
    ):
        return {
            "role": "assistant",
            "content": self.content,
        }


class FakeLLM:

    def chat(
        self,
        messages,
        tools=None,
    ):

        return LLMResponse(
            message=FakeMessage(
                content="Done."
            ),
            usage=TokenUsage(
                prompt_tokens=700,
                completion_tokens=100,
                total_tokens=800,
            ),
        )


def test_loop_updates_context_budget():

    agent = MiniCodexAgent(
        llm=FakeLLM(),
        registry=ToolRegistry(),
        planner=None,
        replanner=None,
        max_steps=1,
        max_context_tokens=1000,
    )

    result = agent.run(
        "Say done.",
        use_planning=False,
    )

    assert (
        result
        == "Done."
    )

    assert (
        agent.context_budget
        .last_prompt_tokens
        == 700
    )

    assert (
        agent.context_budget
        .usage_ratio
        == 0.7
    )

    assert (
        agent.context_budget
        .pressure
        .value
        == "warning"
    )

def test_context_budget_resets_between_tasks():

    agent = MiniCodexAgent(
        llm=FakeLLM(),
        registry=ToolRegistry(),
        planner=None,
        replanner=None,
        max_steps=1,
        max_context_tokens=1000,
    )

    agent.run(
        "Task one.",
        use_planning=False,
    )

    assert (
        agent.context_budget
        .last_prompt_tokens
        == 700
    )

    # run() internally resets before starting
    # the second task, then the new LLM call
    # observes 700 again.
    agent.run(
        "Task two.",
        use_planning=False,
    )

    assert (
        agent.context_budget
        .last_prompt_tokens
        == 700
    )