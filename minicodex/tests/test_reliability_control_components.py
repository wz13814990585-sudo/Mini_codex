import json
from types import SimpleNamespace

from ..agent.progress import ActionController
from ..agent.agent import MiniCodexAgent
from ..agent.dependency import DependencyResolver
from ..agent.editing import EditRetryPolicy
from ..agent.routing import ExecutionMode
from ..agent.routing import policy_for
from ..agent.observability import ExecutionMetrics
from ..agent.task_state import AgentPhase, TaskState
from ..agent.routing import TaskRouter
from ..agent.validation import ValidationOutcome
from ..agent.validation import ValidatorResolver
from ..agent.validation import (
    BrowserAction,
    BrowserAssertion,
    BrowserInteractionContract,
)
from ..agent.validation.plan import EvidenceStrength, ValidationCheck
from ..agent.validation.evidence import ValidationPurpose
from ..agent.memory import WorkingSummary
from ..llm.types import LLMResponse, TokenUsage
from ..evaluation.reliability_cases import BENCHMARKS, FAILURE_BENCHMARKS
from ..tools.base import BaseTool
from ..tools.editing import PatchFileTool
from ..tools.filesystem import ReadFileTool
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
    capabilities = frozenset({"test.run"})
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
    capabilities = frozenset({"process.run"})
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
    from minicodex.agent.task_state import TaskRuntime, RuntimeEventType

    state = TaskState(mode=ExecutionMode.FAST, user_request="fix demo.py")
    runtime = TaskRuntime(state)
    before = state.progress_key()
    state = runtime.emit(RuntimeEventType.TOOL_FINISHED, tool_name="read_file")
    assert state.phase == AgentPhase.INSPECTING
    assert state.progress_key() == before

    state = runtime.emit(RuntimeEventType.EDIT_APPLIED, edit_revision=1)
    assert state.phase == AgentPhase.VALIDATING
    assert state.progress_key() != before

    state = runtime.emit(
        RuntimeEventType.VALIDATION_OBSERVED, outcome=ValidationOutcome.FAILED
    )
    assert state.phase == AgentPhase.FIXING
    state = runtime.emit(
        RuntimeEventType.VALIDATION_OBSERVED, outcome=ValidationOutcome.PASSED
    )
    assert state.phase == AgentPhase.VALIDATING


def test_benchmark_catalog_has_required_mode_mix_and_budgets():
    assert len(BENCHMARKS) >= 12
    modes = {case.expected_mode for case in BENCHMARKS}
    assert modes == {ExecutionMode.FAST, ExecutionMode.STANDARD, ExecutionMode.COMPLEX}
    assert all(case.max_inspections_before_action <= 3 for case in BENCHMARKS)
    assert all(
        not case.requires_plan
        for case in BENCHMARKS
        if case.expected_mode == ExecutionMode.FAST
    )
    assert len(FAILURE_BENCHMARKS) >= 16
    router = TaskRouter()
    assert all(
        router.route(case.prompt).mode == case.expected_mode for case in BENCHMARKS
    )


def test_action_controller_is_phase_aware():
    registry = ToolRegistry()
    registry.register(ReadFileTool("."))

    class SearchTool:
        name = "search_code"
        capabilities = frozenset({"code.search"})

    registry.register(SearchTool())
    registry.register(SequencedTestsTool())
    controller = ActionController(registry)
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

    from dataclasses import replace

    state = replace(state, phase=AgentPhase.FIXING)
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
        data={"path": "demo.py", "failure_type": "stale_context"},
    )
    assert "读取" in policy.observe("patch_file", {"path": "demo.py"}, stale)
    assert policy.restriction_reason("search_code", {"query": "x"})
    assert policy.restriction_reason("read_file", {"path": "demo.py"}) is None

    read = ToolResult(
        success=True, summary="read", data={"path": "demo.py"},
        llm_content="// keyboard behavior missing",
    )
    retry_message = policy.observe("read_file", {"path": "demo.py"}, read)
    assert "重试" in retry_message
    assert "// keyboard behavior missing" in retry_message
    assert "不得改写、概括" in retry_message
    assert "// keyboard behavior missing" in policy.restriction_reason(
        "read_file", {"path": "demo.py"},
    )
    assert policy.restriction_reason("patch_file", {"path": "demo.py"}) is None
    policy.observe(
        "patch_file",
        {"path": "demo.py"},
        ToolResult(success=True, summary="edited", data={"path": "demo.py"}),
    )
    assert policy.pending is None


def test_stale_patch_with_current_content_skips_mandatory_read():
    policy = EditRetryPolicy()
    stale = ToolResult(
        success=False,
        summary="stale",
        data={
            "path": "app.js",
            "failure_type": "stale_context",
            "current_content": "// keyboard behavior missing\n",
        },
    )
    message = policy.observe("patch_file", {"path": "app.js"}, stale)
    assert "CURRENT SOURCE" in message
    assert "// keyboard behavior missing" in message
    assert policy.restriction_reason("read_file", {"path": "app.js"}) is not None
    assert policy.restriction_reason("patch_file", {"path": "app.js"}) is None

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


def test_validator_resolver_uses_check_capability(tmp_path):
    class BrowserTool:
        name = "browser_adapter"
        capabilities = frozenset({"validation.browser"})

    registry = ToolRegistry()
    registry.register(BrowserTool())
    check = ValidationCheck(
        "V1",
        ("R1",),
        ValidationPurpose.ACCEPTANCE,
        BrowserInteractionContract(
            "game.html",
            BrowserAction("keypress", "#score", "ArrowLeft"),
            BrowserAssertion("text_equals", "#score", "1"),
        ),
        strength=EvidenceStrength.RUNTIME,
    )
    resolved = ValidatorResolver(tmp_path).resolve(
        check, registry=registry, paths=("game.html",)
    )
    assert resolved.tool_name == "browser_adapter"
    assert resolved.arguments["validation_check"] == "V1"


def test_working_summary_prioritizes_target_and_actionable_facts():
    summary = WorkingSummary(max_items=10)
    summary.add("已检查 unrelated.py。")
    summary.add("已成功修改文件：app/main.py。")
    summary.add("app/main.py 验证失败。")
    summary.add("已检查 another.py。")
    rendered = summary.render_relevant(("app/main.py",), max_items=2)
    assert "已成功修改文件" in rendered
    assert "验证失败" in rendered
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


def test_failed_tool_execution_is_counted_but_failed_validation_outcome_is_not():
    metrics = ExecutionMetrics()
    failed_edit = ToolResult(False, "patch could not execute")
    executed_validation = ToolResult(
        True,
        "3 tests failed",
        {"outcome": "failed", "failed": 3, "errors": 0},
    )
    metrics.record_tool("patch_file", llm_call_count=1, success=failed_edit.success)
    metrics.record_tool(
        "run_tests", llm_call_count=2, success=executed_validation.success
    )
    assert metrics.failed_tool_call_count == 1
    assert metrics.failed_tool_call_rate == 0.5
    assert metrics.failed_edit_tool_count == 1


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
    assert edited.data["changed"] is True  # End of file.
