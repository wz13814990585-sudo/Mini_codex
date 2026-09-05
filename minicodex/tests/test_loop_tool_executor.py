from types import SimpleNamespace

from ..agent.agent import MiniCodexAgent
from ..agent.tool_executor import (
    PreparedToolCall,
    ToolExecution,
)
from ..llm.types import LLMResponse, TokenUsage
from ..tools.registry import ToolRegistry
from ..tools.results import ToolResult


class FakeResponse:
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

    def model_dump(
        self,
        exclude_none=True,
    ):
        result = {
            "role": "assistant",
        }

        if self.content is not None:
            result["content"] = self.content

        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": (
                            call.function.name
                        ),
                        "arguments": (
                            call.function.arguments
                        ),
                    },
                }
                for call
                in self.tool_calls
            ]

        return result


class FakeLLM:
    def __init__(
        self,
        responses,
    ):
        self.responses = list(
            responses
        )

    def chat(
        self,
        messages,
        tools=None,
    ):
        # Loop expects LLMResponse(message=..., usage=...),
        # matching the real LLMClient contract.
        return LLMResponse(
            message=self.responses.pop(0),
            usage=TokenUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )


class SpyToolExecutor:
    def __init__(self):
        self.prepare_calls = []
        self.execute_calls = []

    def prepare(
        self,
        tool_name: str,
        raw_arguments: str,
    ) -> PreparedToolCall:

        self.prepare_calls.append(
            {
                "tool_name": tool_name,
                "raw_arguments": (
                    raw_arguments
                ),
            }
        )

        return PreparedToolCall(
            tool_name=tool_name,
            arguments={
                "value": 123
            },
        )

    def execute_prepared(
        self,
        prepared: PreparedToolCall,
    ) -> ToolExecution:

        self.execute_calls.append(
            prepared
        )

        return ToolExecution(
            tool_name=(
                prepared.tool_name
            ),
            arguments=(
                prepared.arguments
            ),
            result=ToolResult(
                success=True,
                summary=(
                    "Spy executor executed tool."
                ),
                data={
                    "executed_by": (
                        "spy_executor"
                    ),
                },
            ),
        )


class FailingRegistry(
    ToolRegistry
):
    """
    If AgentLoop tries to execute a tool directly through
    registry.execute(), this test must fail.
    """

    def execute(
        self,
        name: str,
        arguments: dict,
    ):
        raise AssertionError(
            "AgentLoop bypassed ToolExecutor "
            "and called registry.execute directly."
        )


def make_tool_call(
    name: str,
    arguments: str,
):
    return SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name=name,
            arguments=arguments,
        ),
    )


def test_agent_loop_uses_tool_executor():

    tool_call = make_tool_call(
        name="fake_tool",
        arguments='{"value": 123}',
    )

    llm = FakeLLM(
        responses=[
            FakeResponse(
                tool_calls=[
                    tool_call
                ]
            ),
            FakeResponse(
                content="Done.",
                tool_calls=[],
            ),
        ]
    )

    registry = FailingRegistry()

    agent = MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=None,
        replanner=None,
        max_steps=3,
    )

    spy_executor = (
        SpyToolExecutor()
    )

    # Replace the real executor with a spy.
    agent.tool_executor = (
        spy_executor
    )

    result = agent.run(
        "Use the fake tool.",
        use_planning=False,
    )

    assert result == "Done."

    assert (
        len(
            spy_executor.prepare_calls
        )
        == 1
    )

    assert (
        spy_executor.prepare_calls[0][
            "tool_name"
        ]
        == "fake_tool"
    )

    assert (
        spy_executor.prepare_calls[0][
            "raw_arguments"
        ]
        == '{"value": 123}'
    )

    assert (
        len(
            spy_executor.execute_calls
        )
        == 1
    )

    assert (
        spy_executor.execute_calls[0]
        .tool_name
        == "fake_tool"
    )

    assert (
        spy_executor.execute_calls[0]
        .arguments
        == {
            "value": 123
        }
    )