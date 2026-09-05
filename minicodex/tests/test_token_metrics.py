from types import SimpleNamespace

from ..agent.agent import MiniCodexAgent
from ..agent.metrics import TokenMetrics
from ..agent.planner import Planner
from ..llm.types import LLMResponse, TokenUsage
from ..tools.registry import ToolRegistry


class FakeMessage:

    def __init__(
        self,
        *,
        content=None,
        tool_calls=None,
    ):
        self.content = content
        self.tool_calls = (
            tool_calls
            if tool_calls is not None
            else []
        )

    def model_dump(self, exclude_none=True):
        result = {"role": "assistant"}

        if self.content is not None:
            result["content"] = self.content

        if self.tool_calls:
            result["tool_calls"] = [
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

        return result


class PlannerFakeLLM:
    """Returns a fixed plan JSON for planner-only tests."""

    def chat(self, messages, tools=None):
        message = SimpleNamespace(
            content="""
{
    "goal": "Fix calculator",
    "steps": [
        "Inspect calculator",
        "Fix bug",
        "Run tests"
    ]
}
"""
        )

        return LLMResponse(
            message=message,
            usage=TokenUsage(
                prompt_tokens=500,
                completion_tokens=100,
                total_tokens=600,
            ),
        )


class LoopFakeLLM:
    """Returns a final assistant text with no tool calls."""

    def __init__(self):
        self.call_count = 0

    def chat(self, messages, tools=None):
        self.call_count += 1

        if self.call_count == 1:
            return LLMResponse(
                message=FakeMessage(
                    content="Done.",
                    tool_calls=[],
                ),
                usage=TokenUsage(
                    prompt_tokens=1000,
                    completion_tokens=100,
                    total_tokens=1100,
                ),
            )

        raise AssertionError(
            "Unexpected extra LLM call."
        )


class SharedTaskFakeLLM:
    """First call = planner JSON, second call = loop final answer."""

    def __init__(self):
        self.call_count = 0

    def chat(self, messages, tools=None):
        self.call_count += 1

        if self.call_count == 1:
            return LLMResponse(
                message=SimpleNamespace(
                    content="""
{
    "goal": "Simple task",
    "steps": [
        "Finish the task"
    ]
}
"""
                ),
                usage=TokenUsage(
                    prompt_tokens=300,
                    completion_tokens=50,
                    total_tokens=350,
                ),
            )

        if self.call_count == 2:
            return LLMResponse(
                message=FakeMessage(
                    content="Done.",
                    tool_calls=[],
                ),
                usage=TokenUsage(
                    prompt_tokens=700,
                    completion_tokens=100,
                    total_tokens=800,
                ),
            )

        raise AssertionError(
            "Unexpected extra LLM call."
        )


def test_token_metrics_initial_state():
    metrics = TokenMetrics()

    assert metrics.call_count == 0
    assert metrics.total.prompt_tokens == 0
    assert metrics.total.completion_tokens == 0
    assert metrics.total.total_tokens == 0


def test_token_metrics_accumulates_usage():
    metrics = TokenMetrics()

    metrics.record(
        TokenUsage(
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
        )
    )
    metrics.record(
        TokenUsage(
            prompt_tokens=200,
            completion_tokens=30,
            total_tokens=230,
        )
    )

    assert metrics.call_count == 2
    assert metrics.total.prompt_tokens == 300
    assert metrics.total.completion_tokens == 50
    assert metrics.total.total_tokens == 350


def test_token_metrics_reset():
    metrics = TokenMetrics()

    metrics.record(
        TokenUsage(
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
        )
    )
    metrics.reset()

    assert metrics.call_count == 0
    assert metrics.total.prompt_tokens == 0
    assert metrics.total.completion_tokens == 0
    assert metrics.total.total_tokens == 0


def test_planner_records_token_usage():
    metrics = TokenMetrics()
    planner = Planner(llm=PlannerFakeLLM())

    plan = planner.create_plan(
        user_request="Fix calculator bug",
        max_agent_steps=20,
        token_metrics=metrics,
    )

    assert plan.goal == "Fix calculator"
    assert len(plan.steps) == 3
    assert metrics.call_count == 1
    assert metrics.total.prompt_tokens == 500
    assert metrics.total.completion_tokens == 100
    assert metrics.total.total_tokens == 600


def test_agent_loop_records_token_usage():
    llm = LoopFakeLLM()
    registry = ToolRegistry()

    agent = MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=None,
        replanner=None,
        max_steps=3,
    )

    result = agent.run(
        "Say done.",
        use_planning=False,
    )

    assert result == "Done."
    assert agent.token_metrics.call_count == 1
    assert agent.token_metrics.total.prompt_tokens == 1000
    assert agent.token_metrics.total.completion_tokens == 100
    assert agent.token_metrics.total.total_tokens == 1100


def test_agent_resets_token_metrics_between_tasks():
    class MultiTaskFakeLLM:
        def chat(self, messages, tools=None):
            return LLMResponse(
                message=FakeMessage(
                    content="Done.",
                    tool_calls=[],
                ),
                usage=TokenUsage(
                    prompt_tokens=100,
                    completion_tokens=20,
                    total_tokens=120,
                ),
            )

    llm = MultiTaskFakeLLM()
    registry = ToolRegistry()

    agent = MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=None,
        replanner=None,
    )

    agent.run("Task one", use_planning=False)
    assert agent.token_metrics.total.total_tokens == 120

    agent.run("Task two", use_planning=False)

    # Should NOT become 240.
    assert agent.token_metrics.total.total_tokens == 120
    assert agent.token_metrics.call_count == 1


def test_planner_and_loop_share_task_metrics():
    llm = SharedTaskFakeLLM()
    planner = Planner(llm=llm)
    registry = ToolRegistry()

    agent = MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=planner,
        replanner=None,
        max_steps=1,
    )

    agent.run(
        "Do a simple task.",
        use_planning=True,
    )

    assert agent.token_metrics.call_count == 2
    assert agent.token_metrics.total.prompt_tokens == 1000
    assert agent.token_metrics.total.completion_tokens == 150
    assert agent.token_metrics.total.total_tokens == 1150
