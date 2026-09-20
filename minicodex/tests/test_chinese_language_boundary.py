"""Chinese-first productization language boundaries (no real LLM calls)."""

from __future__ import annotations

import inspect
import re
from types import SimpleNamespace

from ..agent.observability.trace import TraceEventType
from ..agent.orchestration.task_report import TaskReportBuilder
from ..agent.planning import Planner, RequirementsExtractor, TaskRequirement
from ..agent.planning.requirements import RequirementCategory, RequirementKind
from ..agent.progress import ActionController, RecoveryController
from ..agent.reason_codes import ReasonCode, display_label
from ..agent.routing import ExecutionMode, TaskIntent, TaskRouter
from ..agent.safety import SafetyPolicy
from ..agent.validation import TaskOutcome, TestVerificationSpec, ValidationPurpose
from ..agent.validation.plan import ValidationCheck
from ..agent.validation.validator_resolver import ResolutionStatus, ValidatorResolver
from ..evaluation.benchmark_v1 import BENCHMARK_VERSION, catalog_by_id
from ..evaluation.models import EvaluationResult, EvaluationSummary
from ..evaluation.reporting import compare_profiles, comparison_markdown
from ..main import run_interactive
from ..prompts.system import SYSTEM_PROMPT
from ..tools.editing import PatchFileTool, WriteFileTool
from ..tools.execution import RunTestsTool
from ..tools.execution.run_tests import parse_pytest_output
from ..tools.filesystem import ListFilesTool, ReadFileTool
from ..tools.registry import ToolRegistry
from ..tools.search import SearchCodeTool


_CJK = re.compile(r"[\u4e00-\u9fff]")


def _has_cjk(text: str) -> bool:
    return bool(_CJK.search(str(text or "")))


def test_router_chinese_modify_intent_and_english_mode_enum():
    decision = TaskRouter(llm=None).route("帮我修复登录接口")
    assert decision.intent == TaskIntent.MODIFY
    assert decision.mode in {
        ExecutionMode.FAST,
        ExecutionMode.STANDARD,
        ExecutionMode.COMPLEX,
    }
    assert isinstance(decision.mode, ExecutionMode)
    assert decision.mode.value in {"fast", "standard", "complex"}


def test_router_fallback_reason_chinese_enums_english():
    decision = TaskRouter(llm=None).route("帮我修复登录接口")
    assert decision.fallback_used is True
    assert _has_cjk(decision.reason)
    assert decision.intent.name == "MODIFY"
    assert decision.mode.name in {"FAST", "STANDARD", "COMPLEX"}


def test_requirements_chinese_description_english_category():
    reqs = RequirementsExtractor(llm=None).extract(
        "帮我修复登录接口",
        mode=ExecutionMode.STANDARD,
    )
    assert reqs.items
    item = reqs.items[0]
    assert _has_cjk(item.description) or _has_cjk(item.observable)
    assert item.category.value in {c.value for c in RequirementCategory}
    assert item.category.value.isascii()
    assert item.kind.value in {k.value for k in RequirementKind}
    assert item.kind.value.isascii()

    manual = TaskRequirement(
        "R1",
        "登录失败应返回 401",
        category=RequirementCategory.BEHAVIOR,
        observable="无效密码返回 401",
    )
    assert manual.category.value == "behavior"
    assert _has_cjk(manual.description)


def test_planner_json_schema_keys_english_with_chinese_instructions():
    source = inspect.getsource(Planner.create_plan)
    for key in ('"goal"', '"steps"', '"acceptance_criteria"'):
        assert key in source
    assert _has_cjk(source)
    assert "你是编码任务规划器" in source


def test_tool_names_unchanged():
    names = {
        ReadFileTool.name,
        PatchFileTool.name,
        WriteFileTool.name,
        RunTestsTool.name,
        ListFilesTool.name,
        SearchCodeTool.name,
        *ActionController.INSPECTION_TOOLS,
        *ActionController.EDIT_TOOLS,
        *ActionController.VALIDATION_TOOLS,
    }
    for expected in (
        "read_file",
        "patch_file",
        "write_file",
        "run_tests",
        "list_files",
        "search_code",
        "replace_lines",
        "validate_static_web",
    ):
        assert expected in names
        assert expected.isascii()


def test_tool_parameter_names_unchanged():
    props = ReadFileTool.parameters["properties"]
    assert "path" in props
    assert set(props).issubset({"path", "offset", "limit"})
    assert all(key.isascii() for key in props)


def test_tool_descriptions_are_chinese_readable():
    for tool_cls in (ReadFileTool, PatchFileTool, RunTestsTool, WriteFileTool):
        description = tool_cls.description
        assert _has_cjk(description)
        assert not description.startswith("Read a file")
        assert not description.startswith("Patch")


def test_task_report_success_blocked_incomplete_chinese():
    builder = TaskReportBuilder()
    agent = SimpleNamespace(
        output_level="normal",
        git_awareness=None,
        validation_pipeline=None,
        task_requirements=None,
    )
    success = builder.build(agent, outcome=TaskOutcome.EDITED_AND_VALIDATED)
    assert success.startswith("任务已成功完成")
    blocked = builder.build(agent, outcome=TaskOutcome.BLOCKED, reason="安全策略拦截")
    assert blocked.startswith("任务被阻塞")
    incomplete = builder.build(agent, outcome=TaskOutcome.INCOMPLETE, reason="证据不足")
    assert incomplete.startswith("任务未完成")


def test_cli_prompt_uses_chinese_you():
    source = inspect.getsource(run_interactive)
    assert 'input("\\n你 > ")' in source or "你 >" in source


def test_action_controller_restriction_messages_chinese():
    assert _has_cjk(ActionController.INSTRUCTION)
    assert "上下文已足够" in ActionController.INSTRUCTION


def test_recovery_warning_chinese():
    message, continue_ = RecoveryController().recover("无进展", lambda _r: {})
    assert continue_ is True
    assert "【恢复" in message
    assert _has_cjk(message)


def test_validator_resolver_human_reason_chinese(tmp_path):
    class Tests:
        name = "run_tests"
        capabilities = frozenset({"test.run"})

    registry = ToolRegistry()
    registry.register(Tests())
    check = ValidationCheck(
        "V1",
        ("R1",),
        ValidationPurpose.ACCEPTANCE,
        spec=TestVerificationSpec("app.py", "tests/missing.py::test_x"),
    )
    resolution = ValidatorResolver(tmp_path).resolve(check, registry=registry)
    assert resolution.status == ResolutionStatus.TARGET_UNRESOLVED
    assert _has_cjk(resolution.reason)


def test_safety_decision_reason_chinese_rule_english(tmp_path):
    decision = SafetyPolicy(workspace=tmp_path).assess(
        "write_file",
        {"path": "../outside.py"},
    )
    assert decision.allowed is False
    assert decision.rule == "workspace_escape"
    assert decision.rule.isascii()
    assert _has_cjk(decision.reason)


def test_reason_code_values_english_display_label_chinese():
    assert ReasonCode.MAX_STEPS.value == "max_steps"
    assert ReasonCode.BLOCKED.value == "blocked"
    assert ReasonCode.STALE_CONTEXT.value == "stale_context"
    assert all(code.value.isascii() and " " not in code.value for code in ReasonCode)
    assert display_label(ReasonCode.MAX_STEPS) == "已达到最大 Agent 步数"
    assert display_label("blocked") == "任务已阻塞"
    assert _has_cjk(display_label(ReasonCode.STALE_CONTEXT))


def test_tool_result_summary_chinese_for_read_file(tmp_path):
    path = tmp_path / "demo.py"
    path.write_text("print(1)\n", encoding="utf-8")
    result = ReadFileTool(workspace=str(tmp_path)).execute(path="demo.py")
    assert result.success is True
    assert _has_cjk(result.summary)
    assert "已读取" in result.summary


def test_tool_result_failure_type_english_on_stale_patch(tmp_path):
    path = tmp_path / "demo.py"
    path.write_text("x = 1\n", encoding="utf-8")
    result = PatchFileTool(workspace=str(tmp_path)).execute(
        path="demo.py",
        old_text="x = 999",
        new_text="x = 2",
    )
    assert result.success is False
    failure_type = result.data["failure_type"]
    assert failure_type == "stale_context"
    assert failure_type.isascii()
    assert _has_cjk(result.summary)


def test_raw_pytest_output_preserves_failed_verbatim():
    stdout = (
        "=========================== FAILURES ===========================\n"
        "FAILED tests/test_math.py::test_double - AssertionError\n"
        "==================== 1 failed in 0.01s ====================\n"
    )
    parsed = parse_pytest_output(exit_code=1, stdout=stdout, stderr="")
    assert any(name.startswith("FAILED ") for name in parsed["failed_tests"])
    assert "FAILED tests/test_math.py::test_double - AssertionError" in parsed["failed_tests"]
    assert parsed["failure_type"] in {None, "regression_failed"}
    if parsed["failure_type"] is not None:
        assert parsed["failure_type"].isascii()


def test_raw_trace_event_values_english():
    assert TraceEventType.LLM_STARTED.value == "llm_started"
    assert TraceEventType.TOOL_FINISHED.value == "tool_finished"
    assert TraceEventType.TASK_FINISHED.value == "task_finished"
    assert all(event.value.isascii() for event in TraceEventType)


def test_benchmark_json_metric_keys_english_markdown_chinese():
    baseline = EvaluationSummary(
        "baseline",
        [EvaluationResult("a", False, "", tool_call_count=4)],
    )
    current = EvaluationSummary(
        "minicodex",
        [EvaluationResult("a", True, "", tool_call_count=2)],
    )
    report = compare_profiles(baseline, current)
    assert "task_success_rate" in report["metrics"]
    assert all(key.isascii() for key in report["metrics"])
    metrics = current.vibe_metrics()
    assert "task_success_rate" in metrics
    assert all(isinstance(key, str) and key.isascii() for key in metrics)

    markdown = comparison_markdown(report)
    assert "对比" in markdown or "指标" in markdown
    assert _has_cjk(markdown)
    assert "# Baseline 与 MiniCodex 对比" in markdown


def test_benchmark_v1_prompt_english_and_version_constant():
    fixture = catalog_by_id()["fix_python_double"]
    prompt = fixture.case.prompt
    assert "Fix src/pkg/maths.py" in prompt
    assert prompt.isascii()
    assert BENCHMARK_VERSION == "minicodex-bench-v1"


def test_system_prompt_is_chinese():
    assert "你是 MiniCodex" in SYSTEM_PROMPT
    assert _has_cjk(SYSTEM_PROMPT)
