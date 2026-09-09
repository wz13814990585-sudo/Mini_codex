import json
from types import SimpleNamespace

from ...agent.agent import MiniCodexAgent
from ...agent.routing import ExecutionMode
from ...agent.orchestration.message_protocol import validate_tool_message_protocol
from ...llm.types import LLMResponse, TokenUsage
from ...tools.base import BaseTool
from ...tools.filesystem import ReadFileTool
from ...tools.registry import ToolRegistry
from ...tools.results import ToolResult
from ...tools.editing import WriteFileTool


class StaticPassTool(BaseTool):
    name = "validate_static_web"
    description = "Validate static web"
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


def tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class ToolMessage:
    def __init__(self, call):
        self.content = None
        self.tool_calls = [call]

    def model_dump(self, exclude_none=True):
        call = self.tool_calls[0]
        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
            ],
        }


class BatchMessage:
    content = None

    def __init__(self, calls):
        self.tool_calls = list(calls)

    def model_dump(self, exclude_none=True):
        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ],
        }


class CountingTool(BaseTool):
    name = "git_diff"
    description = "Diff"
    parameters = {"type": "object", "properties": {}}

    def __init__(self):
        self.calls = 0

    def execute(self):
        self.calls += 1
        return ToolResult(success=True, summary="diff")


class AcceptanceCommandTool(BaseTool):
    name = "run_command"
    description = "Run acceptance command"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "purpose": {"type": "string"},
        },
    }

    def execute(self, command, purpose="diagnostic"):
        return ToolResult(
            success=True,
            summary="Acceptance command passed",
            data={"command_succeeded": True, "exit_code": 0},
        )


class AcceptanceTestsTool(BaseTool):
    name = "run_tests"
    description = "Run targeted tests"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "purpose": {"type": "string"},
        },
    }

    def execute(self, path=".", purpose="regression"):
        return ToolResult(
            success=True,
            summary="1 passed",
            data={
                "tests_passed": True,
                "passed": 1,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
            },
        )


class ScriptedLLM:
    def __init__(self, calls):
        self.script = list(calls)
        self.calls = 0
        self.schemas = []

    def chat(self, messages, tools=None):
        validate_tool_message_protocol(messages)
        self.calls += 1
        self.schemas.append(tuple(schema["function"]["name"] for schema in tools))
        return LLMResponse(
            message=ToolMessage(self.script.pop(0)),
            usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        )


def fast_agent(tmp_path, llm, *, include_read=False):
    registry = ToolRegistry()
    if include_read:
        registry.register(ReadFileTool(tmp_path))
    registry.register(WriteFileTool(tmp_path))
    registry.register(StaticPassTool())
    planner = SimpleNamespace(
        create_plan=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("FAST benchmark must not call Planner")
        )
    )
    replanner = SimpleNamespace(
        replan=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("FAST benchmark must not call Replanner")
        )
    )
    return MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=planner,
        replanner=replanner,
        repo_map=None,
        max_steps=20,
        status_interval_seconds=0,
    )


def test_benchmark_hello_html_edits_validates_and_finishes(tmp_path):
    llm = ScriptedLLM(
        [
            tool_call(
                "write",
                "write_file",
                {
                    "path": "try_code/hello.html",
                    "content": "<html><body>Hello World</body></html>",
                },
            ),
            tool_call(
                "validate",
                "validate_static_web",
                {"path": "try_code/hello.html"},
            ),
        ]
    )
    agent = fast_agent(tmp_path, llm)
    result = agent.run("Create try_code/hello.html with a Hello World page.")

    assert agent.execution_policy.mode == ExecutionMode.FAST
    assert agent.active_plan is None
    assert llm.calls == 2
    assert agent.execution_metrics.tool_call_count == 2
    assert agent.execution_metrics.calls_before_first_edit == 1
    assert agent.execution_metrics.final_outcome == "edited_and_validated"
    assert "Outcome:" not in result
    assert all("complete_plan_step" not in schemas for schemas in llm.schemas)
    assert all("replan" not in schemas for schemas in llm.schemas)


def test_benchmark_existing_tetris_finishes_without_edit(tmp_path):
    target = tmp_path / "try_code/index.html"
    target.parent.mkdir(parents=True)
    target.write_text(
        "<html><body><canvas></canvas><script>const tetris=true;</script></body></html>",
        encoding="utf-8",
    )
    llm = ScriptedLLM(
        [
            tool_call("read", "read_file", {"path": "try_code/index.html"}),
            tool_call(
                "validate",
                "validate_static_web",
                {"path": "try_code/index.html"},
            ),
        ]
    )
    agent = fast_agent(tmp_path, llm, include_read=True)
    result = agent.run("Create a Tetris game in try_code/index.html.")

    assert llm.calls == 2
    assert agent.validation_pipeline.state.has_edit is False
    assert agent.execution_metrics.edit_tool_count == 0
    assert agent.execution_metrics.inspection_tool_count == 1
    assert agent.execution_metrics.validation_tool_count == 1
    assert agent.execution_metrics.final_outcome == "already_satisfied"
    assert "Task already satisfied." in result


def test_fast_validation_pass_does_not_request_another_llm_round(tmp_path):
    llm = ScriptedLLM(
        [
            tool_call(
                "write",
                "write_file",
                {
                    "path": "try_code/index.html",
                    "content": "<html><body><script>let game = 1;</script></body></html>",
                },
            ),
            tool_call(
                "validate",
                "validate_static_web",
                {"path": "try_code/index.html"},
            ),
        ]
    )
    agent = fast_agent(tmp_path, llm)
    agent.run("在 try_code/index.html 中做一个俄罗斯方块小游戏")

    assert llm.calls == 2
    assert not llm.script


def test_fast_immediate_completion_closes_remaining_provider_batch(tmp_path):
    trailing = CountingTool()
    registry = ToolRegistry()
    registry.register(WriteFileTool(tmp_path))
    registry.register(StaticPassTool())
    registry.register(trailing)

    class OneBatchLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools=None):
            validate_tool_message_protocol(messages)
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("FAST completion requested an extra LLM round")
            return LLMResponse(
                message=BatchMessage(
                    [
                        tool_call(
                            "write",
                            "write_file",
                            {
                                "path": "try_code/game.html",
                                "content": "<html><body>game</body></html>",
                            },
                        ),
                        tool_call(
                            "validate",
                            "validate_static_web",
                            {"path": "try_code/game.html"},
                        ),
                        tool_call("diff", "git_diff", {}),
                    ]
                ),
                usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
            )

    llm = OneBatchLLM()
    agent = MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=None,
        repo_map=None,
        status_interval_seconds=0,
    )
    result = agent.run("Create try_code/game.html")

    assert llm.calls == 1
    assert trailing.calls == 0
    assert agent.execution_metrics.final_outcome == "edited_and_validated"


def test_benchmark_readme_is_planless_and_skips_full_regression(tmp_path):
    registry = ToolRegistry()
    registry.register(WriteFileTool(tmp_path))
    registry.register(AcceptanceCommandTool())
    llm = ScriptedLLM(
        [
            tool_call(
                "write",
                "write_file",
                {"path": "README.md", "content": "# Setup\n\nRun `pip install -e .`."},
            ),
            tool_call(
                "validate",
                "run_command",
                {"command": "test -s README.md", "purpose": "acceptance"},
            ),
        ]
    )
    agent = MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=None,
        repo_map=None,
        status_interval_seconds=0,
    )
    result = agent.run("Update README.md with setup instructions.")

    assert agent.execution_policy.mode == ExecutionMode.FAST
    assert agent.active_plan is None
    assert llm.calls == 2
    assert agent.execution_metrics.validation_tool_count == 1
    assert agent.validation_pipeline.state.full_passed is False
    assert agent.execution_metrics.final_outcome == "edited_and_validated"


def test_benchmark_small_python_edit_reaches_action_and_targeted_validation(tmp_path):
    registry = ToolRegistry()
    registry.register(WriteFileTool(tmp_path))
    registry.register(AcceptanceTestsTool())
    llm = ScriptedLLM(
        [
            tool_call(
                "write",
                "write_file",
                {
                    "path": "examples/helper.py",
                    "content": (
                        "def square(value):\n"
                        "    if not isinstance(value, int):\n"
                        "        raise TypeError('value must be int')\n"
                        "    return value * value\n"
                    ),
                },
            ),
            tool_call(
                "validate",
                "run_tests",
                {"path": "examples/test_helper.py", "purpose": "acceptance"},
            ),
        ]
    )
    agent = MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=None,
        repo_map=None,
        status_interval_seconds=0,
    )
    result = agent.run("Add input validation to one existing Python function.")

    assert agent.execution_policy.mode == ExecutionMode.FAST
    assert llm.calls == 2
    assert agent.execution_metrics.calls_before_first_edit == 1
    assert agent.execution_metrics.final_outcome == "edited_and_validated"
    assert agent.execution_metrics.final_outcome == "edited_and_validated"
