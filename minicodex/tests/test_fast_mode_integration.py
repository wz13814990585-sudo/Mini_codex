import json
from types import SimpleNamespace

from ..agent.agent import MiniCodexAgent
from ..agent.execution_mode import ExecutionMode
from ..agent.message_protocol import validate_tool_message_protocol
from ..llm.types import LLMResponse, TokenUsage
from ..tools.base import BaseTool
from ..tools.registry import ToolRegistry
from ..tools.results import ToolResult
from ..tools.write_file import WriteFileTool


class StaticPassTool(BaseTool):
    name = "validate_static_web"
    description = "Validate a static page."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def execute(self, path):
        return ToolResult(
            success=True,
            summary=f"Static web validation passed for {path}",
            data={"outcome": "passed", "errors": []},
        )


def call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments),
        ),
    )


class Message:
    def __init__(self, tool_calls):
        self.content = None
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=True):
        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": item.id,
                    "type": "function",
                    "function": {
                        "name": item.function.name,
                        "arguments": item.function.arguments,
                    },
                }
                for item in self.tool_calls
            ],
        }


class FastGameLLM:
    def __init__(self):
        self.calls = 0
        self.histories = []

    def chat(self, messages, tools=None):
        validate_tool_message_protocol(messages)
        self.calls += 1
        self.histories.append(messages)
        tool = (
            call(
                "write",
                "write_file",
                {
                    "path": "try_code/index.html",
                    "content": (
                        "<html><body><canvas></canvas>"
                        "<script>let score = 0;</script></body></html>"
                    ),
                },
            )
            if self.calls == 1
            else call(
                "validate",
                "validate_static_web",
                {"path": "try_code/index.html"},
            )
        )
        return LLMResponse(
            message=Message([tool]),
            usage=TokenUsage(
                prompt_tokens=20,
                completion_tokens=10,
                total_tokens=30,
            ),
        )


def test_tetris_html_uses_fast_edit_validate_finish_path(tmp_path):
    registry = ToolRegistry()
    registry.register(WriteFileTool(tmp_path))
    registry.register(StaticPassTool())
    llm = FastGameLLM()
    agent = MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=SimpleNamespace(
            create_plan=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("FAST must not invoke Planner")
            )
        ),
        repo_map=None,
        max_steps=20,
        status_interval_seconds=0,
    )

    result = agent.run(
        "Create a Tetris game in try_code/index.html"
    )

    assert agent.execution_policy.mode == ExecutionMode.FAST
    assert agent.active_plan is None
    assert agent.task_max_steps == 8
    assert llm.calls == 2
    assert (tmp_path / "try_code/index.html").is_file()
    assert agent.validation_pipeline.state.acceptance_passed is True
    assert agent.validation_pipeline.state.full_passed is False
    assert "Task completed" in result
    assert agent.execution_metrics.final_outcome == "edited_and_validated"
