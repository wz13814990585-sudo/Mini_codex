import json
from types import SimpleNamespace

from ....agent.agent import MiniCodexAgent
from ....llm.types import LLMResponse, TokenUsage
from ....tools.base import BaseTool
from ....tools.registry import ToolRegistry
from ....tools.read_file import ReadFileTool
from ....tools.results import ToolResult
from ....tools.write_file import WriteFileTool


def response(*, content=None, call_id=None, tool=None, arguments=None):
    calls = []
    if tool:
        calls = [
            SimpleNamespace(
                id=call_id,
                function=SimpleNamespace(name=tool, arguments=json.dumps(arguments or {})),
            )
        ]

    class Message:
        tool_calls = calls

        def __init__(self):
            self.content = content

        def model_dump(self, exclude_none=True):
            payload = {"role": "assistant"}
            if self.content is not None:
                payload["content"] = self.content
            if calls:
                payload["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in calls
                ]
            return payload

    return Message()


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.histories = []

    def chat(self, messages, tools=None):
        self.histories.append(list(messages))
        message = self.responses.pop(0)
        return LLMResponse(message=message, usage=TokenUsage())


class StaticValidator(BaseTool):
    name = "validate_static_web"
    description = "Validate static HTML"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}}

    def execute(self, path):
        return ToolResult(
            success=True,
            summary=f"Static web validation passed for {path}",
            data={"path": path, "outcome": "passed", "failed_count": 0},
        )


def make_agent(tmp_path, llm):
    registry = ToolRegistry()
    registry.register(WriteFileTool(tmp_path))
    registry.register(ReadFileTool(tmp_path))
    registry.register(StaticValidator())
    return MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=None,
        repo_map=None,
        status_interval_seconds=0,
    )


def test_coding_explanation_is_rejected_once_then_tools_complete(tmp_path):
    llm = ScriptedLLM(
        [
            response(content="You can create an HTML file."),
            response(
                call_id="write",
                tool="write_file",
                arguments={"path": "try_code/demo.html", "content": "<html></html>"},
            ),
            response(
                call_id="validate",
                tool="validate_static_web",
                arguments={"path": "try_code/demo.html"},
            ),
        ]
    )
    agent = make_agent(tmp_path, llm)

    report = agent.run("Create try_code/demo.html")

    assert len(llm.histories) == 3
    assert agent.completion_handler.EXECUTION_CORRECTION in {
        message.get("content") for message in llm.histories[1] if message["role"] == "user"
    }
    assert (tmp_path / "try_code/demo.html").is_file()
    assert agent.execution_metrics.final_outcome == "edited_and_validated"
    assert "EDITED_AND_VALIDATED" not in report


def test_ready_coding_task_returns_harness_report_without_extra_llm(tmp_path):
    llm = ScriptedLLM(
        [
            response(
                call_id="write",
                tool="write_file",
                arguments={"path": "try_code/demo.html", "content": "<html></html>"},
            ),
            response(
                call_id="validate",
                tool="validate_static_web",
                arguments={"path": "try_code/demo.html"},
            ),
        ]
    )

    agent = make_agent(tmp_path, llm)
    report = agent.run("Create try_code/demo.html")

    assert len(llm.histories) == 2
    assert report.startswith("Task completed successfully.")
    assert "try_code/demo.html" in report


def test_informational_request_returns_normal_model_text(tmp_path):
    llm = ScriptedLLM([response(content="It loads the selected file and validates its path.")])
    agent = make_agent(tmp_path, llm)

    answer = agent.run("Explain how read_file works")

    assert answer == "It loads the selected file and validates its path."
    assert agent.execution_metrics.final_outcome == "informational_answer"


def test_existing_artifact_reports_already_satisfied(tmp_path):
    target = tmp_path / "try_code/demo.html"
    target.parent.mkdir(parents=True)
    target.write_text("<html></html>", encoding="utf-8")
    llm = ScriptedLLM(
        [
            response(
                call_id="validate",
                tool="validate_static_web",
                arguments={"path": "try_code/demo.html"},
            )
        ]
    )

    agent = make_agent(tmp_path, llm)
    report = agent.run("Create try_code/demo.html")

    assert "Task already satisfied." in report
    assert agent.execution_metrics.final_outcome == "already_satisfied"
    assert "ALREADY_SATISFIED" not in report


def test_concrete_blocker_becomes_harness_blocked_report(tmp_path):
    llm = ScriptedLLM([response(content="BLOCKED: required credential is unavailable")])

    agent = make_agent(tmp_path, llm)
    report = agent.run("Create try_code/demo.html")

    assert report.startswith("Task blocked.")
    assert "required credential is unavailable" in report
    assert agent.execution_metrics.final_outcome == "blocked"
    assert "Outcome:" not in report


def test_inspect_only_reads_target_then_allows_findings_without_edit_tools(tmp_path):
    target = tmp_path / "examples/helper.py"
    target.parent.mkdir(parents=True)
    target.write_text("def value():\n    return None\n", encoding="utf-8")
    llm = ScriptedLLM(
        [
            response(
                call_id="read",
                tool="read_file",
                arguments={"path": "examples/helper.py"},
            ),
            response(content="The function always returns None."),
        ]
    )
    agent = make_agent(tmp_path, llm)

    result = agent.run("Review examples/helper.py but do not modify it")

    exposed = {
        schema["function"]["name"]
        for schema in agent.get_tool_schemas()
    }
    assert "write_file" not in exposed
    assert "patch_file" not in exposed
    assert result == "The function always returns None."
    assert agent.execution_metrics.final_outcome == "inspected"


def test_debug_output_keeps_machine_outcome_in_report(tmp_path):
    llm = ScriptedLLM(
        [
            response(
                call_id="write",
                tool="write_file",
                arguments={"path": "try_code/demo.html", "content": "<html></html>"},
            ),
            response(
                call_id="validate",
                tool="validate_static_web",
                arguments={"path": "try_code/demo.html"},
            ),
        ]
    )
    agent = make_agent(tmp_path, llm)
    agent.output_level = "debug"

    report = agent.run("Create try_code/demo.html")

    assert "EDITED_AND_VALIDATED (edited_and_validated)" in report


def test_normal_output_suppresses_control_plane_noise(tmp_path, capsys):
    llm = ScriptedLLM([response(content="pytest -q runs tests quietly.")])
    agent = make_agent(tmp_path, llm)

    result = agent.run("What does pytest -q mean?")

    assert result == "pytest -q runs tests quietly."
    assert capsys.readouterr().out == ""
