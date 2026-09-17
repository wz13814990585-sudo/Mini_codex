"""Executable offline VibeBench scenarios using the canonical EvaluationHarness.

Run: python -m minicodex.evaluation.vibebench
Scripts replace only the model: editing, command validation and completion are real.
"""
from contextlib import redirect_stdout
from dataclasses import dataclass
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from .harness import EvaluationHarness
from .models import EvaluationCase, EvaluationCheck
from ..agent.agent import MiniCodexAgent
from ..agent.orchestration.message_protocol import validate_tool_message_protocol
from ..llm.types import LLMResponse, TokenUsage
from ..tools.registry import ToolRegistry
from ..tools.editing import PatchFileTool, WriteFileTool
from ..tools.filesystem import ReadFileTool
from ..tools.execution import RunCommandTool
from ..tools.execution import RunTestsTool
from ..tools.validation.validate_static_web import ValidateStaticWebTool
from ..tools.validation.validate_service import ValidateServiceTool


class ScriptedModel:
    def __init__(self, script):
        self.script = iter(script)
        self.sequence = 0

    def chat(self, messages, tools=None):
        validate_tool_message_protocol(messages)
        name, arguments = next(self.script)
        self.sequence += 1
        call_id = str(self.sequence)
        call = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
        message = SimpleNamespace(content=None, tool_calls=[call])
        message.model_dump = lambda **kwargs: {"role": "assistant", "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
        return LLMResponse(message, TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))


@dataclass(frozen=True)
class Scenario:
    case: EvaluationCase
    files: tuple[tuple[str, str], ...]
    script: tuple[tuple[str, dict], ...]
    warmup_script: tuple[tuple[str, dict], ...] = ()
    warmup_prompt: str = ""


def assertion(path, expected, check="V1"):
    command = f'python -c "from pathlib import Path; assert Path(\'{path}\').read_text() == \'{expected}\\n\'"'
    return "run_command", {"command": command, "purpose": "acceptance", "validation_check": check}


def patch(path, before, after):
    return "patch_file", {"path": path, "old_text": before, "new_text": after}


def scenarios():
    a, b = "examples/a.py", "examples/b.py"
    def case(name, prompt, paths=((a, "VALUE = 2"),)):
        return EvaluationCase(name, prompt, tuple(EvaluationCheck("file_contains", value, path) for path, value in paths))
    def behavior(code, check="V1"):
        import shlex
        return "run_command", {"command": "python -c " + shlex.quote(code), "purpose": "acceptance", "validation_check": check}
    calc = "examples/calc.py"
    base = (
        Scenario(case("tiny_edit", f"Set VALUE to 2 in {a}."), ((a, "VALUE = 1\n"),),
                 (patch(a, "VALUE = 1", "VALUE = 2"), assertion(a, "VALUE = 2"))),
        Scenario(case("already_satisfied", f"Set VALUE to 2 in {a}."), ((a, "VALUE = 2\n"),),
                 (assertion(a, "VALUE = 2"),)),
        Scenario(case("create_file", f"Create {a} with VALUE = 2."), (),
                 (("write_file", {"path": a, "content": "VALUE = 2\n"}), assertion(a, "VALUE = 2"))),
        Scenario(case("unknown_repository", f"Fix VALUE to 2 in {a}."), ((a, "VALUE = 1\n"),),
                 (("read_file", {"path": a}), patch(a, "VALUE = 1", "VALUE = 2"), assertion(a, "VALUE = 2"))),
        Scenario(case("local_repair", f"Fix VALUE to 2 in {a}."), ((a, "VALUE = 1\n"),),
                 (patch(a, "VALUE = 1", "VALUE = 3"), assertion(a, "VALUE = 2"),
                  patch(a, "VALUE = 3", "VALUE = 2"), assertion(a, "VALUE = 2"))),
        Scenario(case("multifile_requirements", f"Set VALUE to 2 in {a}; set VALUE to 3 in {b}.", ((a, "VALUE = 2"), (b, "VALUE = 3"))),
                 ((a, "VALUE = 1\n"), (b, "VALUE = 1\n")),
                 (patch(a, "VALUE = 1", "VALUE = 2"), patch(b, "VALUE = 1", "VALUE = 3"),
                  assertion(a, "VALUE = 2"), assertion(b, "VALUE = 3", "V2"))),
    )
    server = ("from http.server import BaseHTTPRequestHandler, HTTPServer\nimport sys\n"
              "class Handler(BaseHTTPRequestHandler):\n"
              "    def do_GET(self):\n"
              "        self.send_response(200)\n        self.end_headers()\n        self.wfile.write(b'old')\n"
              "HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()\n")
    return base + (
        Scenario(case("local_bug", f"Fix double in {calc} to multiply by two.", ((calc, "value * 2"),)),
                 ((calc, "def double(value):\n    return value + 2\n"),),
                 (patch(calc, "value + 2", "value * 2"), behavior("from examples.calc import double; assert double(3) == 6"))),
        Scenario(case("small_feature", f"Add zero handling to {calc} reciprocal.", ((calc, "if value == 0"),)),
                 ((calc, "def reciprocal(value):\n    return 1 / value\n"),),
                 (patch(calc, "    return 1 / value", "    if value == 0:\n        return None\n    return 1 / value"),
                  behavior("from examples.calc import reciprocal; assert reciprocal(0) is None; assert reciprocal(2) == .5"))),
        Scenario(case("python_cli", "Create examples/cli.py to print hello.", (("examples/cli.py", "print('hello')"),)), (),
                 (("write_file", {"path": "examples/cli.py", "content": "print('hello')\n"}),
                  behavior("import subprocess,sys; assert subprocess.check_output([sys.executable,'examples/cli.py']).strip() == b'hello'"))),
        Scenario(case("refactor", "Create examples/core.py with double; update examples/client.py to use it.",
                      (("examples/core.py", "def double"), ("examples/client.py", "from examples.core import double"))),
                 (("examples/client.py", "def run():\n    return 3 * 2\n"),),
                 (("write_file", {"path": "examples/core.py", "content": "def double(x):\n    return x * 2\n"}),
                  ("write_file", {"path": "examples/client.py", "content": "from examples.core import double\ndef run():\n    return double(3)\n"}),
                  behavior("from examples.core import double; assert double(3) == 6"),
                  behavior("from examples.client import run; assert run() == 6", "V2"))),
        Scenario(case("api_service", "Fix examples/server.py HTTP response to ready.", (("examples/server.py", "b'ready'"),)),
                 (("examples/server.py", server),),
                 (patch("examples/server.py", "b'old'", "b'ready'"),
                  ("validate_service", {"argv": ["python", "examples/server.py", "{port}"], "port": 0,
                                        "path": "/", "expected_text": "ready", "validation_check": "V1"}))),
        Scenario(case("html_page", "Create examples/hello.html with a Hello heading.", (("examples/hello.html", "<h1>Hello</h1>"),)), (),
                 (("write_file", {"path": "examples/hello.html", "content": "<!doctype html><html><head><title>Hello</title></head><body><h1>Hello</h1></body></html>"}),
                  ("validate_static_web", {"path": "examples/hello.html", "expected_text": "<h1>Hello</h1>", "validation_check": "V1"}))),
        Scenario(case("dependency_constraint", "Update examples/requirements.txt dependency pin to examplelib==2 without installing dependencies.", (("examples/requirements.txt", "examplelib==2"),)),
                 (("examples/requirements.txt", "examplelib==1\n"),),
                 (patch("examples/requirements.txt", "examplelib==1", "examplelib==2"), assertion("examples/requirements.txt", "examplelib==2"))),
        Scenario(case("failing_test", f"Fix failing double behavior in {calc}.", ((calc, "value * 2"),)),
                 ((calc, "def double(value):\n    return value + 2\n"),
                  ("tests/test_calc.py", "from examples.calc import double\ndef test_double():\n    assert double(3) == 6\n")),
                 (("run_tests", {"path": "tests/test_calc.py::test_double", "purpose": "acceptance", "validation_check": "V1"}),
                  patch(calc, "value + 2", "value * 2"),
                  ("run_tests", {"path": "tests/test_calc.py::test_double", "purpose": "acceptance", "validation_check": "V1"}))),
        Scenario(case("followup", f"Set VALUE to 3 in {a}.", ((a, "VALUE = 3"),)), ((a, "VALUE = 1\n"),),
                 (patch(a, "VALUE = 2", "VALUE = 3"), assertion(a, "VALUE = 3")),
                 (patch(a, "VALUE = 1", "VALUE = 2"), assertion(a, "VALUE = 2")), f"Set VALUE to 2 in {a}."),
    )


def run_vibebench(root, *, model_factory=None, output_level="normal"):
    """Opt-in live evaluation supplies model_factory; no live calls by default."""
    catalog = {s.case.case_id: s for s in scenarios()}
    def factory(case):
        scenario = catalog[case.case_id]
        workspace = Path(root) / case.case_id
        workspace.mkdir(parents=True, exist_ok=True)
        for path, content in scenario.files:
            file = workspace / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        registry = ToolRegistry()
        for tool in (ReadFileTool, PatchFileTool, WriteFileTool, RunCommandTool, RunTestsTool, ValidateStaticWebTool, ValidateServiceTool):
            registry.register(tool(workspace))
        script = []
        for name, arguments in scenario.script:
            arguments = dict(arguments)
            if name == "validate_service" and arguments.get("port") == 0:
                import socket
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    arguments["port"] = sock.getsockname()[1]
            script.append((name, arguments))
        model = model_factory(case) if model_factory else ScriptedModel(script)
        agent = MiniCodexAgent(llm=model, registry=registry, planner=None, status_interval_seconds=0, output_level=output_level)
        if scenario.warmup_script:
            agent.llm = model_factory(case) if model_factory else ScriptedModel(scenario.warmup_script)
            agent.run(scenario.warmup_prompt)
            agent.llm = model
        return agent
    return EvaluationHarness(agent_factory=factory).run_suite(run_name="vibebench", cases=[s.case for s in catalog.values()])


if __name__ == "__main__":
    with TemporaryDirectory(prefix="minicodex-vibebench-") as directory:
        with redirect_stdout(io.StringIO()):
            summary = run_vibebench(directory)
        print(json.dumps(summary.to_dict(), indent=2))
