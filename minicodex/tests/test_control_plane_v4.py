import json
from types import SimpleNamespace

from ..agent.action_controller import ActionController
from ..agent.agent import MiniCodexAgent
from ..agent.dependency_resolver import DependencyResolver
from ..agent.edit_retry import EditRetryPolicy
from ..agent.execution_mode import ExecutionMode
from ..agent.execution_policy import policy_for
from ..agent.metrics import ExecutionMetrics
from ..agent.task_state import AgentPhase, TaskState
from ..agent.task_router import TaskRouter
from ..agent.validation import ValidationOutcome
from ..agent.validation_selector import ValidationSelector
from ..agent.working_summary import WorkingSummary
from ..llm.types import LLMResponse, TokenUsage
from ..evaluation.benchmarks_v4 import BENCHMARKS_V4, FAILURE_BENCHMARKS_V4
from ..tools.base import BaseTool
from ..tools.patch_file import PatchFileTool
from ..tools.read_file import ReadFileTool
from ..tools.registry import ToolRegistry
from ..tools.results import ToolResult


def tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class ToolMessage:
    content = None

    def __init__(self, call):
        self.tool_calls = [call]

    def model_dump(self, exclude_none=True):
        call = self.tool_calls[0]
        return {
            "role": "assistant",
            "tool_calls": [{
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }],
        }


class ScriptedLLM:
    def __init__(self, calls):
        self.calls = list(calls)
        self.call_count = 0

    def chat(self, messages, tools=None):
        self.call_count += 1
        return LLMResponse(
            message=ToolMessage(self.calls.pop(0)),
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


class SequencedTestsTool(BaseTool):
    name = "run_tests"
    description = "Focused tests"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, outcomes=(True,)):
        self.outcomes = list(outcomes)

    def execute(self, path=".", purpose="regression"):
        passed = self.outcomes.pop(0)
        return ToolResult(
            success=True,
            summary="1 passed" if passed else "1 failed",
            data={
                "tests_passed": passed,
                "passed": int(passed),
                "failed": int(not passed),
                "errors": 0,
                "skipped": 0,
                "path": path,
                "purpose": purpose,
                "outcome": "passed" if passed else "failed",
                "failed_count": int(not passed),
            },
        )


class NeverRunCommand(BaseTool):
    name = "run_command"
    description = "Command"
    parameters = {"type": "object", "properties": {}}

    def __init__(self):
        self.calls = 0

    def execute(self, command, purpose="diagnostic"):
        self.calls += 1
        return ToolResult(success=True, summary="should not execute")


def make_fast_agent(tmp_path, llm, *, tests=(True,), command=None):
    registry = ToolRegistry()
    registry.register(ReadFileTool(tmp_path))
    registry.register(PatchFileTool(tmp_path))
    registry.register(SequencedTestsTool(tests))
    if command is not None:
        registry.register(command)
    return MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=None,
        repo_map=None,
        status_interval_seconds=0,
    )


def test_task_state_phase_machine_and_progress_key():
    state = TaskState(mode=ExecutionMode.FAST, user_request="fix demo.py")
    before = state.progress_key()
    state.transition_for_tool("read_file", success=True)
    assert state.phase == AgentPhase.INSPECTING
    assert state.progress_key() == before

    state.edit_revision = 1
    state.transition_for_tool("patch_file", success=True)
    assert state.phase == AgentPhase.VALIDATING
    assert state.progress_key() != before

    state.transition_for_tool(
        "run_tests", success=True, validation_outcome=ValidationOutcome.FAILED
    )
    assert state.phase == AgentPhase.FIXING
    state.transition_for_tool(
        "run_tests", success=True, validation_outcome=ValidationOutcome.PASSED
    )
    assert state.phase == AgentPhase.FINALIZING


def test_v4_benchmark_catalog_has_required_mode_mix_and_budgets():
    assert len(BENCHMARKS_V4) >= 12
    modes = {case.expected_mode for case in BENCHMARKS_V4}
    assert modes == {ExecutionMode.FAST, ExecutionMode.STANDARD, ExecutionMode.COMPLEX}
    assert all(case.max_inspections_before_action <= 3 for case in BENCHMARKS_V4)
    assert all(not case.requires_plan for case in BENCHMARKS_V4 if case.expected_mode == ExecutionMode.FAST)
    assert len(FAILURE_BENCHMARKS_V4) == 4
    router = TaskRouter()
    assert all(
        router.route(case.prompt).mode == case.expected_mode
        for case in BENCHMARKS_V4
    )


def test_action_controller_is_phase_aware():
    controller = ActionController()
    policy = policy_for(ExecutionMode.STANDARD)
    state = TaskState(phase=AgentPhase.VALIDATING, edit_revision=1)
    controller.reset(state)
    controller.update_context(
        state=state,
        policy=policy,
        remaining_budget=5,
        acceptance_missing=True,
    )
    assert controller.restriction_reason("search_code", {}, policy)
    assert controller.restriction_reason("run_tests", {}, policy) is None

    state.phase = AgentPhase.FIXING
    controller.update_context(
        state=state,
        policy=policy,
        remaining_budget=4,
        acceptance_missing=True,
    )
    assert controller.restriction_reason("search_code", {}, policy)
    assert controller.restriction_reason("read_file", {}, policy) is None


def test_edit_retry_policy_allows_one_read_and_one_retry():
    policy = EditRetryPolicy()
    stale = ToolResult(
        success=False,
        summary="stale",
        data={"path": "demo.py", "failure_type": "stale_context", "start_line": 2},
    )
    assert "read" in policy.observe("replace_lines", {"path": "demo.py"}, stale).lower()
    assert policy.restriction_reason("search_code", {"query": "x"})
    assert policy.restriction_reason("read_file", {"path": "demo.py"}) is None

    read = ToolResult(success=True, summary="read", data={"path": "demo.py"})
    assert "retry" in policy.observe("read_file", {"path": "demo.py"}, read).lower()
    assert policy.restriction_reason("patch_file", {"path": "demo.py"}) is None
    policy.observe(
        "patch_file",
        {"path": "demo.py"},
        ToolResult(success=True, summary="edited", data={"path": "demo.py"}),
    )
    assert policy.pending is None


def test_dependency_resolver_declared_undeclared_and_standalone(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="demo"\nversion="0.1"\ndependencies=["requests>=2"]\n',
        encoding="utf-8",
    )
    resolver = DependencyResolver(tmp_path)
    declared = resolver.resolve("requests>=2.31")
    assert declared.declared is True
    assert declared.install_allowed is True

    undeclared = resolver.resolve("httpx")
    assert undeclared.install_allowed is False
    assert undeclared.action == "update_manifest_first"
    assert undeclared.preferred_manifest == "pyproject.toml"

    standalone = resolver.resolve("httpx", target_paths=("try_code/demo.py",))
    assert standalone.install_allowed is True
    assert standalone.standalone is True


def test_validation_selector_has_browser_extension_point():
    selector = ValidationSelector()
    static = selector.select(
        target_paths=("try_code/game.html",),
        registered_tools={"validate_static_web"},
    )
    assert static.tool_name == "validate_static_web"
    browser = selector.select(
        target_paths=("try_code/game.html",),
        registered_tools={"validate_static_web", "validate_browser_app"},
        runtime_behavior=True,
    )
    assert browser.tool_name == "validate_browser_app"


def test_working_summary_prioritizes_target_and_actionable_facts():
    summary = WorkingSummary(max_items=10)
    summary.add("Inspected unrelated.py.")
    summary.add("Modified file successfully: app/main.py.")
    summary.add("Validation failed for app/main.py.")
    summary.add("Inspected another.py.")
    rendered = summary.render_relevant(("app/main.py",), max_items=2)
    assert "Modified file" in rendered
    assert "Validation failed" in rendered
    assert "unrelated.py" not in rendered


def test_execution_metrics_include_v4_fields():
    metrics = ExecutionMetrics()
    metrics.reset("fast")
    metrics.observe_llm(call_count=1, total_prompt_tokens=20)
    metrics.record_tool("read_file", llm_call_count=1)
    metrics.record_tool("patch_file", llm_call_count=2)
    metrics.record_tool(
        "run_tests",
        llm_call_count=3,
        arguments={"purpose": "acceptance"},
    )
    metrics.record_rollback()
    assert metrics.llm_call_count == 3
    assert metrics.calls_before_first_edit == 2
    assert metrics.calls_before_first_validation == 3
    assert metrics.rollback_count == 1
    assert metrics.total_prompt_tokens == 20


def test_structured_stale_patch_and_edit_metadata(tmp_path):
    path = tmp_path / "demo.py"
    path.write_text("value = 2\n", encoding="utf-8")
    tool = PatchFileTool(tmp_path)
    stale = tool.execute("demo.py", "value = 1", "value = 3")
    assert stale.success is False
    assert stale.data["path"] == "demo.py"
    assert stale.data["checkpoint_id"] is None
    assert stale.data["changed"] is False
    assert stale.data["edit_kind"] == "exact_patch"
    assert stale.data["failure_type"] == "stale_context"
    assert stale.data["retry_action"] == "read_target_region_then_retry_once"
    edited = tool.execute("demo.py", "value = 2", "value = 3")
    assert edited.data["edit_kind"] == "exact_patch"
    assert edited.data["changed"] is True


def test_failure_benchmark_stale_patch_reads_target_then_retries(tmp_path):
    target = tmp_path / "examples/helper.py"
    target.parent.mkdir(parents=True)
    target.write_text("def value():\n    return 0\n", encoding="utf-8")
    llm = ScriptedLLM([
        tool_call("stale", "patch_file", {
            "path": "examples/helper.py", "old_text": "return 1", "new_text": "return 2"
        }),
        tool_call("read", "read_file", {"path": "examples/helper.py"}),
        tool_call("retry", "patch_file", {
            "path": "examples/helper.py", "old_text": "return 0", "new_text": "return 2"
        }),
        tool_call("validate", "run_tests", {
            "path": "examples/test_helper.py", "purpose": "acceptance"
        }),
    ])
    agent = make_fast_agent(tmp_path, llm)
    result = agent.run("Fix a simple Python bug in examples/helper.py.")
    assert llm.call_count == 4
    assert "return 2" in target.read_text(encoding="utf-8")
    assert agent.execution_metrics.calls_before_first_edit == 3
    assert agent.task_state.phase == AgentPhase.DONE
    assert "edited_and_validated" in result


def test_failure_benchmark_validation_fail_fix_revalidate(tmp_path):
    target = tmp_path / "examples/helper.py"
    target.parent.mkdir(parents=True)
    target.write_text("def value():\n    return 0\n", encoding="utf-8")
    llm = ScriptedLLM([
        tool_call("edit1", "patch_file", {
            "path": "examples/helper.py", "old_text": "return 0", "new_text": "return 1"
        }),
        tool_call("fail", "run_tests", {
            "path": "examples/test_helper.py", "purpose": "acceptance"
        }),
        tool_call("read", "read_file", {"path": "examples/helper.py"}),
        tool_call("edit2", "patch_file", {
            "path": "examples/helper.py", "old_text": "return 1", "new_text": "return 2"
        }),
        tool_call("pass", "run_tests", {
            "path": "examples/test_helper.py", "purpose": "acceptance"
        }),
    ])
    agent = make_fast_agent(tmp_path, llm, tests=(False, True))
    result = agent.run("Fix a simple Python bug in examples/helper.py.")
    assert llm.call_count == 5
    assert agent.validation_pipeline.state.acceptance_passed is True
    assert "return 2" in target.read_text(encoding="utf-8")
    assert "edited_and_validated" in result


def test_failure_benchmark_unsafe_command_then_safe_edit(tmp_path):
    target = tmp_path / "examples/helper.py"
    target.parent.mkdir(parents=True)
    target.write_text("value = 0\n", encoding="utf-8")
    command = NeverRunCommand()
    llm = ScriptedLLM([
        tool_call("unsafe", "run_command", {"command": "rm -rf examples"}),
        tool_call("safe", "patch_file", {
            "path": "examples/helper.py", "old_text": "value = 0", "new_text": "value = 1"
        }),
        tool_call("validate", "run_tests", {
            "path": "examples/test_helper.py", "purpose": "acceptance"
        }),
    ])
    agent = make_fast_agent(tmp_path, llm, command=command)
    result = agent.run("Fix a simple Python bug in examples/helper.py.")
    assert command.calls == 0
    assert target.read_text(encoding="utf-8") == "value = 1\n"
    assert "edited_and_validated" in result
