import json
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from ..agent.planning.requirements import (
    RequirementCategory,
    RequirementsExtractor,
    TaskRequirement,
    TaskRequirements,
)
from ..agent.routing import ExecutionMode
from ..agent.runtime.tool_executor import ToolExecutor
from ..agent.validation import (
    BrowserAction,
    BrowserAssertion,
    BrowserInteractionContract,
    BrowserNoOpBehavior,
    CompletionStatus,
    FileExistsContract,
    HttpContract,
    NodeBehaviorContract,
    PythonBehaviorContract,
    TaskCompletionPolicy,
    TaskOutcome,
    TestTargetContract,
    ValidationEvidence,
    ValidationExecutor,
    ValidationOutcome,
    ValidationPipeline,
    ValidationPurpose,
    ValidationScope,
    ValidatorResolver,
    RegressionRequirement,
)
from ..evaluation.harness import EvaluationHarness
from ..agent.observability.trace import TraceEventType, TraceRecorder
from ..agent.observability.metrics import ExecutionMetrics
from ..agent.orchestration.tool_result_handlers import (
    EditResultHandler,
    ValidationResultHandler,
)
from ..agent.validation.executor import ValidationExecutionState
from ..agent.validation.plan import EvidenceStrength, ValidationPlanner
from ..agent.validation.validator_resolver import ResolutionStatus, ValidatorResolution
from ..tools.registry import ToolRegistry
from ..tools.results import ToolResult
from ..tools.execution import RunCommandTool
from ..tools.validation.validate_service import ValidateServiceTool
from ..llm.types import LLMResponse, TokenUsage


class _TestsTool:
    name = "run_tests"
    capabilities = frozenset({"test.run"})
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}

    def __init__(self, results=None):
        self.results = list(results or [True])
        self.calls = 0

    def execute(self, path, purpose="regression"):
        self.calls += 1
        passed = self.results.pop(0)
        return ToolResult(True, "executed", {
            "tests_passed": passed,
            "passed": int(passed),
            "failed": int(not passed),
            "errors": 0,
            "skipped": 0,
        })


class CommandTool:
    name = "run_command"
    capabilities = frozenset({"process.run"})
    parameters = {
        "type": "object",
        "properties": {"command": {"type": "string"}, "purpose": {"type": "string"}},
        "required": ["command"],
    }

    def __init__(self):
        self.calls = 0

    def execute(self, command, purpose="diagnostic"):
        self.calls += 1
        return ToolResult(True, "executed", {"command_succeeded": True, "exit_code": 0})


class ServiceTool:
    name = "validate_service"
    capabilities = frozenset({"service.validate"})


def requirements(*contracts):
    return TaskRequirements([
        TaskRequirement(f"R{i}", f"需求 {i}", contract=contract)
        for i, contract in enumerate(contracts, 1)
    ])


def planned(*contracts):
    pipeline = ValidationPipeline()
    pipeline.state.plan = ValidationPlanner().build(requirements(*contracts))
    return pipeline


def test_identical_contract_is_one_multi_requirement_check():
    contract = PythonBehaviorContract("from pkg import add; assert add(2, 3) == 5")
    pipeline = planned(contract, contract)
    assert len(pipeline.state.plan.checks) == 1
    assert pipeline.state.plan.checks[0].requirement_ids == ("R1", "R2")


def test_unbound_acceptance_cannot_prove_required_check():
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    pipeline.observe("run_tests", {"path": "tests/test_x.py", "purpose": "acceptance"},
                     ToolResult(True, "pass", {"tests_passed": True, "passed": 1}))
    assert pipeline.state.proof("V1") is None


@pytest.mark.parametrize("failure_type", [
    "duplicate_call", "action_required_restriction", "schema_validation",
    "safety_blocked", "tool_unavailable",
])
def test_non_executed_validator_never_creates_evidence(failure_type):
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    result = ToolResult(False, "not executed", {"failure_type": failure_type})
    assert pipeline.observe("run_tests", {
        "path": "tests/test_x.py", "purpose": "acceptance", "validation_check": "V1",
    }, result) is None
    assert pipeline.state.evidence_history == []


def test_pass_then_non_execution_remains_stable_pass():
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    resolution = ValidatorResolution(
        "V1", ResolutionStatus.RESOLVED, "run_tests", {},
        "test.run", "tests/test_x.py", "pytest|tests/test_x.py",
    )
    passed = pipeline.observe("run_tests", {
        "path": "tests/test_x.py", "purpose": "acceptance",
    }, ToolResult(True, "pass", {"tests_passed": True, "passed": 1}), resolution=resolution)
    pipeline.observe("run_tests", {
        "path": "tests/test_x.py", "purpose": "acceptance",
    }, ToolResult(False, "duplicate", {"failure_type": "duplicate_call"}), resolution=resolution)
    assert passed.unstable is False
    assert pipeline.state.proof("V1") is passed


def test_pass_then_executed_fail_is_contradictory():
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    resolution = ValidatorResolution(
        "V1", ResolutionStatus.RESOLVED, "run_tests", {},
        "test.run", "tests/test_x.py", "pytest|tests/test_x.py",
    )
    pipeline.observe("run_tests", {"path": "tests/test_x.py", "purpose": "acceptance"},
                     ToolResult(True, "pass", {"tests_passed": True, "passed": 1}),
                     resolution=resolution)
    failed = pipeline.observe("run_tests", {"path": "tests/test_x.py", "purpose": "acceptance"},
                              ToolResult(True, "fail", {"tests_passed": False, "failed": 1}),
                              resolution=resolution)
    assert failed.unstable is True
    assert pipeline.state.proof("V1") is None


def test_inconclusive_does_not_erase_prior_pass():
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    resolution = ValidatorResolution(
        "V1", ResolutionStatus.RESOLVED, "run_tests", {},
        "test.run", "tests/test_x.py", "pytest|tests/test_x.py",
    )
    proof = pipeline.observe("run_tests", {"path": "tests/test_x.py", "purpose": "acceptance"},
                             ToolResult(True, "pass", {"tests_passed": True, "passed": 1}),
                             resolution=resolution)
    pipeline.observe("run_tests", {"path": "tests/test_x.py", "purpose": "acceptance"},
                     ToolResult(True, "no tests", {"tests_passed": False, "failed": 0, "errors": 0}),
                     resolution=resolution)
    assert pipeline.state.proof("V1") is proof


def test_chinese_file_description_uses_typed_path_not_description(tmp_path):
    (tmp_path / "index.html").write_text("nothing from description")
    requirement = TaskRequirement(
        "R1", "仓库根目录下存在 index.html 文件",
        RequirementCategory.FILE, ("index.html",), FileExistsContract("index.html"),
    )
    check = ValidationPlanner().build(TaskRequirements([requirement])).checks[0]
    registry = ToolRegistry()
    registry.register(CommandTool())
    resolution = ValidatorResolver(tmp_path).resolve(check, registry=registry)
    assert resolution.status == ResolutionStatus.RESOLVED
    assert "仓库根目录" not in resolution.arguments["command"]


def _execute_browser_fallback(
    tmp_path, html, javascript, action, assertion, *, contract_path="index.html",
    non_target=None,
):
    html_path = tmp_path / "index.html"
    script_path = tmp_path / "app.js"
    html_path.write_text(html, encoding="utf-8")
    script_path.write_text(javascript, encoding="utf-8")
    before = {
        html_path: html_path.read_bytes(),
        script_path: script_path.read_bytes(),
    }
    contract = BrowserInteractionContract(
        contract_path, action, assertion, non_target,
    )
    check = ValidationPlanner().build(requirements(contract)).checks[0]
    registry = ToolRegistry()
    registry.register(CommandTool())
    resolution = ValidatorResolver(tmp_path).resolve(check, registry=registry)
    assert resolution.status == ResolutionStatus.RESOLVED
    assert resolution.capability == "process.run"
    completed = subprocess.run(
        shlex.split(resolution.arguments["command"]),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert {path: path.read_bytes() for path in before} == before
    return completed


_KEYBOARD_HTML = """\
<div id="state">idle</div>
<script type="module" src="./app.js"></script>
"""
_KEYBOARD_JS = """\
const state = document.getElementById("state");
document.addEventListener("keydown", event => {
  if (event.key === "ArrowLeft") {
    state.textContent = "left";
  }
});
"""


def test_browser_node_fallback_executes_target_key_against_initial_html(tmp_path):
    completed = _execute_browser_fallback(
        tmp_path, _KEYBOARD_HTML, _KEYBOARD_JS,
        BrowserAction("keypress", "#state", "ArrowLeft"),
        BrowserAssertion("text_equals", "#state", "left"),
    )
    assert completed.returncode == 0, completed.stderr


def test_browser_node_fallback_preserves_initial_text_for_unrelated_key(tmp_path):
    completed = _execute_browser_fallback(
        tmp_path, _KEYBOARD_HTML, _KEYBOARD_JS,
        BrowserAction("keypress", "#state", "x"),
        BrowserAssertion("text_equals", "#state", "idle"),
    )
    assert completed.returncode == 0, completed.stderr


def test_browser_node_fallback_finds_html_state_from_javascript_contract(tmp_path):
    completed = _execute_browser_fallback(
        tmp_path, _KEYBOARD_HTML, _KEYBOARD_JS,
        BrowserAction("keypress", "#state", "x"),
        BrowserAssertion("text_equals", "#state", "idle"),
        contract_path="app.js",
    )
    assert completed.returncode == 0, completed.stderr


def test_browser_node_fallback_executes_counter_click(tmp_path):
    completed = _execute_browser_fallback(
        tmp_path,
        """\
<button id="increment">+</button>
<span id="count">0</span>
<script type="module" src="./app.js"></script>
""",
        """\
const count = document.getElementById("count");
document.getElementById("increment").addEventListener("click", () => {
  count.textContent = String(Number(count.textContent) + 1);
});
""",
        BrowserAction("click", "#increment"),
        BrowserAssertion("text_equals", "#count", "1"),
    )
    assert completed.returncode == 0, completed.stderr


def test_browser_node_fallback_fails_when_unrelated_key_mutates_state(tmp_path):
    completed = _execute_browser_fallback(
        tmp_path, _KEYBOARD_HTML,
        """\
const state = document.getElementById("state");
document.addEventListener("keydown", () => {
  state.textContent = "left";
});
""",
        BrowserAction("keypress", "#state", "x"),
        BrowserAssertion("text_equals", "#state", "idle"),
    )
    assert completed.returncode != 0


class _TypedRequirementsLLM:
    model = "offline-typed-requirements"

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append((messages, tools))
        return LLMResponse(
            SimpleNamespace(content=json.dumps(self.payload), tool_calls=[]),
            TokenUsage(),
        )


def _execute_keyboard_requirement(workspace, requirements, javascript):
    workspace.mkdir()
    (workspace / "index.html").write_text(_KEYBOARD_HTML, encoding="utf-8")
    (workspace / "app.js").write_text(javascript, encoding="utf-8")
    plan = ValidationPlanner().build(requirements)
    check = plan.checks[0]
    registry = ToolRegistry()
    registry.register(RunCommandTool(workspace))
    resolution = ValidatorResolver(workspace).resolve(check, registry=registry)
    pipeline = ValidationPipeline()
    pipeline.state.plan = plan
    pipeline.record_edit()
    agent = SimpleNamespace(
        registry=registry,
        tool_executor=ToolExecutor(registry),
        validation_pipeline=pipeline,
        token_metrics=SimpleNamespace(call_count=0),
        execution_metrics=None,
        refresh_workspace_facts=lambda: None,
    )
    result = ValidationExecutor().execute(agent, check, resolution)
    return check, resolution, result


def test_keyboard_prompt_to_executor_proves_trigger_and_non_target_no_op(tmp_path):
    prompt = (
        "Update app.js so pressing ArrowLeft changes #state text from idle to left; "
        "other keys leave it unchanged."
    )
    llm = _TypedRequirementsLLM({
        "requirements": [{
            "description": "ArrowLeft 改变状态，其他按键不改变状态",
            "category": "behavior",
            "paths": ["app.js"],
            "contract": {
                "type": "browser_interaction",
                "path": "app.js",
                "action": {
                    "type": "keypress", "selector": "#state", "value": "ArrowLeft",
                },
                "assertion": {
                    "type": "text_equals", "selector": "#state", "value": "left",
                },
                "non_target": {
                    "action": {"type": "keypress", "selector": "#state", "value": "x"},
                    "assertion": {
                        "type": "text_equals", "selector": "#state", "value": "idle",
                    },
                },
            },
        }],
        "policy": {"no_edit_if_already_satisfied": False},
    })
    extracted = RequirementsExtractor(llm).extract(
        prompt, mode=ExecutionMode.STANDARD, target_paths=("app.js",),
    )
    assert llm.calls[0][0][-1]["content"] == prompt
    contract = extracted.items[0].contract
    assert isinstance(contract, BrowserInteractionContract)
    assert isinstance(contract.non_target, BrowserNoOpBehavior)

    correct = _execute_keyboard_requirement(tmp_path / "correct", extracted, _KEYBOARD_JS)
    assert correct[0].contract is contract
    assert correct[1].status == ResolutionStatus.RESOLVED
    assert correct[2].state == ValidationExecutionState.PROVEN

    every_key_left = """\
const state = document.getElementById("state");
document.addEventListener("keydown", () => {
  state.textContent = "left";
});
"""
    wrong = _execute_keyboard_requirement(tmp_path / "wrong", extracted, every_key_left)
    assert wrong[1].status == ResolutionStatus.RESOLVED
    assert wrong[2].state == ValidationExecutionState.FAILED


def test_unavailable_browser_without_fallback_is_blocked(tmp_path):
    contract = BrowserInteractionContract(
        "index.html", BrowserAction("click", "#x"),
        BrowserAssertion("text_equals", "", ""),
    )
    check = ValidationPlanner().build(requirements(contract)).checks[0]
    resolution = ValidatorResolver(tmp_path).resolve(check, registry=ToolRegistry())
    assert resolution.status == ResolutionStatus.TARGET_UNRESOLVED


def test_node_contract_resolves_to_targeted_command(tmp_path):
    check = ValidationPlanner().build(requirements(
        NodeBehaviorContract("if (2 + 3 !== 5) process.exit(1)")
    )).checks[0]
    registry = ToolRegistry()
    registry.register(CommandTool())
    resolution = ValidatorResolver(tmp_path).resolve(check, registry=registry)
    assert resolution.status == ResolutionStatus.RESOLVED
    assert "node --input-type=module" in resolution.arguments["command"]


def test_manual_node_command_cannot_prove_contract():
    pipeline = planned(NodeBehaviorContract("if (sum([]) !== 0) process.exit(1)"))
    pipeline.observe("run_command", {
        "command": "node -e 'process.exit(0)'", "purpose": "acceptance",
    }, ToolResult(True, "ok", {"command_succeeded": True}))
    assert pipeline.state.proof("V1") is None


def test_wrong_validation_target_counts_only_explicit_proof_attempts():
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    metrics = ExecutionMetrics()
    agent = SimpleNamespace(
        validation_pipeline=pipeline,
        checkpoint_manager=SimpleNamespace(all_checkpoints=lambda: ()),
        task_state=SimpleNamespace(work_unit=None, recovery_level=0),
        workspace=".",
        sync_requirements_state=lambda: None,
        plan_orchestrator=SimpleNamespace(reconcile=lambda _agent: (None, False)),
        validation_orchestrator=SimpleNamespace(apply=lambda **_kwargs: None),
        latest_progress_signal=None,
        current_validation_check=None,
        current_validator_resolution=None,
    )
    handler = ValidationResultHandler()
    result = ToolResult(
        True, "diagnostic pass",
        {"command_succeeded": True, "outcome": "passed"},
    )

    handler.apply(
        agent, tool_name="run_command",
        arguments={"command": "python -c 'print(1)'", "purpose": "acceptance"},
        result=result, capabilities=frozenset({"process.run"}), metrics=metrics,
        emit=lambda *_args, **_kwargs: None,
    )
    assert metrics.wrong_validation_target_count == 0

    bound = handler.apply(
        agent, tool_name="run_command",
        arguments={
            "command": "python -c 'print(1)'",
            "purpose": "acceptance",
            "validation_check": "V1",
        },
        result=ToolResult(
            True, "bound pass",
            {"command_succeeded": True, "outcome": "passed"},
        ),
        capabilities=frozenset({"process.run"}), metrics=metrics,
        emit=lambda *_args, **_kwargs: None,
    )
    assert metrics.wrong_validation_target_count == 1
    assert bound.evidence is not None
    assert bound.evidence.check_id == ""
    assert pipeline.state.proof("V1") is None

    handler.apply(
        agent, tool_name="run_command",
        arguments={
            "command": "python -c 'print(1)'",
            "purpose": "acceptance",
            "validation_check": "V999",
        },
        result=ToolResult(
            True, "wrong target pass",
            {"command_succeeded": True, "outcome": "passed"},
        ),
        capabilities=frozenset({"process.run"}), metrics=metrics,
        emit=lambda *_args, **_kwargs: None,
    )
    assert metrics.wrong_validation_target_count == 2


def test_unrelated_llm_validation_cannot_prove_current_prepared_check():
    pipeline = planned(FileExistsContract("app.py"))
    metrics = ExecutionMetrics()
    check = pipeline.state.plan.checks[0]
    agent = SimpleNamespace(
        validation_pipeline=pipeline,
        checkpoint_manager=SimpleNamespace(all_checkpoints=lambda: ()),
        task_state=SimpleNamespace(work_unit=None, recovery_level=0),
        workspace=".",
        sync_requirements_state=lambda: None,
        plan_orchestrator=SimpleNamespace(reconcile=lambda _agent: (None, False)),
        validation_orchestrator=SimpleNamespace(apply=lambda **_kwargs: None),
        latest_progress_signal=None,
        current_validation_check=check,
        current_validator_resolution=ValidatorResolution(
            check.id, ResolutionStatus.RESOLVED, target="app.py",
            validation_key="file_exists|app.py",
        ),
    )
    handled = ValidationResultHandler().apply(
        agent, tool_name="run_command",
        arguments={"command": "python -c 'print(1)'", "purpose": "acceptance"},
        result=ToolResult(True, "ok", {"command_succeeded": True}),
        capabilities=frozenset({"process.run"}), metrics=metrics,
        emit=lambda *_args, **_kwargs: None,
    )
    assert metrics.wrong_validation_target_count == 0
    assert handled.evidence is not None
    assert handled.evidence.check_id == ""
    assert pipeline.state.proof("V1") is None


def test_exact_prepared_llm_validation_can_prove_current_check():
    pipeline = planned(FileExistsContract("app.py"))
    metrics = ExecutionMetrics()
    check = pipeline.state.plan.checks[0]
    arguments = {
        "command": "python -c \"from pathlib import Path; assert Path('app.py').is_file()\"",
        "purpose": "acceptance",
        "validation_check": "V1",
    }
    resolution = ValidatorResolution(
        check.id,
        ResolutionStatus.RESOLVED,
        tool_name="run_command",
        arguments=arguments,
        capability="process.run",
        target="app.py",
        validation_key="file_exists|app.py",
    )
    agent = SimpleNamespace(
        validation_pipeline=pipeline,
        checkpoint_manager=SimpleNamespace(all_checkpoints=lambda: ()),
        task_state=SimpleNamespace(work_unit=None, recovery_level=0),
        workspace=".",
        sync_requirements_state=lambda: None,
        plan_orchestrator=SimpleNamespace(reconcile=lambda _agent: (None, False)),
        validation_orchestrator=SimpleNamespace(apply=lambda **_kwargs: None),
        latest_progress_signal=None,
        current_validation_check=check,
        current_validator_resolution=resolution,
    )

    handled = ValidationResultHandler().apply(
        agent,
        tool_name="run_command",
        arguments=arguments,
        result=ToolResult(True, "ok", {"command_succeeded": True}),
        capabilities=frozenset({"process.run"}),
        metrics=metrics,
        emit=lambda *_args, **_kwargs: None,
    )

    assert handled.evidence is not None
    assert handled.evidence.check_id == "V1"
    assert pipeline.state.proof("V1") is handled.evidence


def test_resolved_executor_runs_without_llm_decision(tmp_path):
    tool = _TestsTool([True])
    registry = ToolRegistry()
    registry.register(tool)
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_x.py").write_text("def test_x(): pass")
    check = pipeline.state.plan.checks[0]
    resolution = ValidatorResolver(tmp_path).resolve(check, registry=registry)
    agent = SimpleNamespace(
        registry=registry,
        tool_executor=ToolExecutor(registry),
        validation_pipeline=pipeline,
        token_metrics=SimpleNamespace(call_count=0),
        execution_metrics=None,
        refresh_workspace_facts=lambda: None,
        trace_recorder=TraceRecorder(),
    )
    result = ValidationExecutor().execute(agent, check, resolution)
    assert result.state == ValidationExecutionState.PROVEN
    assert tool.calls == 1
    assert pipeline.state.proof("V1")
    event = agent.trace_recorder.events[-1]
    assert event.event_type == TraceEventType.VALIDATION_EVIDENCE
    assert event.data["check_ids"] == ["V1"]
    assert event.data["proof_accepted"] is True


def test_proven_check_is_cached_and_not_reexecuted(tmp_path):
    tool = _TestsTool([True])
    registry = ToolRegistry()
    registry.register(tool)
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_x.py").write_text("def test_x(): pass")
    check = pipeline.state.plan.checks[0]
    resolution = ValidatorResolver(tmp_path).resolve(check, registry=registry)
    agent = SimpleNamespace(
        registry=registry, tool_executor=ToolExecutor(registry),
        validation_pipeline=pipeline, token_metrics=SimpleNamespace(call_count=0),
        execution_metrics=None, refresh_workspace_facts=lambda: None,
    )
    executor = ValidationExecutor()
    assert executor.execute(agent, check, resolution).state == ValidationExecutionState.PROVEN
    assert executor.execute(agent, check, resolution).state == ValidationExecutionState.SKIPPED
    assert tool.calls == 1


def test_completion_reads_ledger_not_requirement_mutation():
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    agent = SimpleNamespace(validation_pipeline=pipeline)
    assert TaskCompletionPolicy().evaluate(agent).status == CompletionStatus.NEEDS_ACCEPTANCE


def test_no_edit_acceptance_pass_is_already_satisfied():
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    resolution = ValidatorResolution(
        "V1", ResolutionStatus.RESOLVED, "run_tests", {},
        "test.run", "tests/test_x.py", "pytest|tests/test_x.py",
    )
    pipeline.observe("run_tests", {"path": "tests/test_x.py", "purpose": "acceptance"},
                     ToolResult(True, "pass", {"tests_passed": True, "passed": 1}),
                     resolution=resolution)
    decision = TaskCompletionPolicy().evaluate(SimpleNamespace(validation_pipeline=pipeline))
    assert decision.status == CompletionStatus.READY
    assert decision.outcome == TaskOutcome.ALREADY_SATISFIED


def test_no_edit_completion_respects_explicit_change_policy():
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    resolution = ValidatorResolution(
        "V1", ResolutionStatus.RESOLVED, "run_tests", {},
        "test.run", "tests/test_x.py", "pytest|tests/test_x.py",
    )
    pipeline.observe(
        "run_tests",
        {"path": "tests/test_x.py", "purpose": "acceptance"},
        ToolResult(True, "pass", {"tests_passed": True, "passed": 1}),
        resolution=resolution,
    )
    required_change = SimpleNamespace(
        validation_pipeline=pipeline,
        task_requirements=TaskRequirements(
            requirements(TestTargetContract("tests/test_x.py")).items,
            no_edit_if_already_satisfied=False,
        ),
    )
    decision = TaskCompletionPolicy().evaluate(required_change)
    assert decision.status == CompletionStatus.NOT_READY
    assert decision.can_complete is False
    assert "要求实施变更" in decision.reason


def test_no_edit_completion_is_allowed_only_when_policy_opts_in():
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    resolution = ValidatorResolution(
        "V1", ResolutionStatus.RESOLVED, "run_tests", {},
        "test.run", "tests/test_x.py", "pytest|tests/test_x.py",
    )
    pipeline.observe(
        "run_tests",
        {"path": "tests/test_x.py", "purpose": "acceptance"},
        ToolResult(True, "pass", {"tests_passed": True, "passed": 1}),
        resolution=resolution,
    )
    opt_in = SimpleNamespace(
        validation_pipeline=pipeline,
        task_requirements=TaskRequirements(
            requirements(TestTargetContract("tests/test_x.py")).items,
            no_edit_if_already_satisfied=True,
        ),
    )
    assert TaskCompletionPolicy().evaluate(opt_in).outcome == TaskOutcome.ALREADY_SATISFIED


def test_completion_requires_policy_regression_obligation_after_edit():
    pipeline = planned(FileExistsContract("app.py"))
    pipeline.record_edit()
    acceptance = pipeline.state.plan.checks[0]
    resolution = ValidatorResolution(
        acceptance.id,
        ResolutionStatus.RESOLVED,
        "run_command",
        {},
        "process.run",
        "app.py",
        "file_exists|app.py",
    )
    pipeline.observe(
        "run_command",
        {"command": "check app.py", "purpose": "acceptance"},
        ToolResult(True, "pass", {"command_succeeded": True}),
        resolution=resolution,
    )
    agent = SimpleNamespace(
        validation_pipeline=pipeline,
        current_regression_requirement=lambda: RegressionRequirement.RELEVANT_ONLY,
    )

    decision = TaskCompletionPolicy().evaluate(agent)

    assert decision.status == CompletionStatus.NEEDS_RELEVANT_VALIDATION
    assert decision.can_complete is False


def test_completion_requires_full_check_for_required_regression():
    pipeline = planned(FileExistsContract("app.py"))
    pipeline.record_edit()
    checks = list(pipeline.state.plan.checks)
    checks.append(type(checks[0])(
        id="V2",
        requirement_ids=(),
        purpose=ValidationPurpose.REGRESSION,
        contract=TestTargetContract("tests/test_app.py"),
        strength=EvidenceStrength.REGRESSION,
        revision=pipeline.state.edit_revision,
    ))
    pipeline.state.plan = type(pipeline.state.plan)(tuple(checks))
    for check in pipeline.state.plan.checks:
        resolution = ValidatorResolution(
            check.id,
            ResolutionStatus.RESOLVED,
            "run_tests" if check.id == "V2" else "run_command",
            {},
            "test.run" if check.id == "V2" else "process.run",
            "tests/test_app.py" if check.id == "V2" else "app.py",
            f"proof|{check.id}",
        )
        if check.id == "V2":
            pipeline.observe(
                "run_tests",
                {"path": "tests/test_app.py", "purpose": "regression"},
                ToolResult(True, "pass", {"tests_passed": True, "passed": 1}),
                resolution=resolution,
            )
        else:
            pipeline.observe(
                "run_command",
                {"command": "check app.py", "purpose": "acceptance"},
                ToolResult(True, "pass", {"command_succeeded": True}),
                resolution=resolution,
            )
    agent = SimpleNamespace(
        validation_pipeline=pipeline,
        current_regression_requirement=lambda: RegressionRequirement.REQUIRED,
    )

    decision = TaskCompletionPolicy().evaluate(agent)

    assert decision.status == CompletionStatus.NEEDS_FULL_VALIDATION
    assert decision.can_complete is False


def test_edit_invalidates_previous_proof():
    pipeline = planned(TestTargetContract("tests/test_x.py"))
    resolution = ValidatorResolution(
        "V1", ResolutionStatus.RESOLVED, "run_tests", {},
        "test.run", "tests/test_x.py", "pytest|tests/test_x.py",
    )
    pipeline.observe("run_tests", {"path": "tests/test_x.py", "purpose": "acceptance"},
                     ToolResult(True, "pass", {"tests_passed": True, "passed": 1}),
                     resolution=resolution)
    assert pipeline.state.proof("V1")
    pipeline.record_edit()
    assert pipeline.state.proof("V1") is None


def test_http_environment_failure_then_pass_closes_check():
    pipeline = planned(HttpContract("POST", "/login", 401))
    resolution = ValidatorResolution(
        "V1", ResolutionStatus.RESOLVED, "validate_service", {},
        "service.validate", "POST /login", "http|POST /login",
    )
    assert pipeline.observe("validate_service", {"path": "/login", "purpose": "acceptance"},
                            ToolResult(False, "port conflict", {"failure_type": "environment_failure"}),
                            frozenset({"service.validate"}), resolution=resolution) is None
    pipeline.observe("validate_service", {"path": "/login", "purpose": "acceptance"},
                     ToolResult(True, "401", {"outcome": "passed", "errors": []}),
                     frozenset({"service.validate"}), resolution=resolution)
    assert pipeline.state.proof("V1")


def test_flask_http_contract_prefers_real_service_probe_without_project_command(tmp_path):
    (tmp_path / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n",
        encoding="utf-8",
    )
    check = ValidationPlanner().build(
        requirements(HttpContract("GET", "/health", 200, '"status": "ok"'))
    ).checks[0]
    registry = ToolRegistry()
    registry.register(CommandTool())
    registry.register(ServiceTool())

    resolution = ValidatorResolver(tmp_path).resolve(
        check, registry=registry, paths=("app.py",),
    )

    assert resolution.tool_name == "validate_service"
    assert resolution.capability == "service.validate"
    assert resolution.arguments["argv"][-2:] == ["{port}", "--no-reload"]
    assert resolution.arguments["path"] == "/health"


def test_service_json_fragment_ignores_only_insignificant_json_whitespace():
    assert ValidateServiceTool._response_contains(
        '{"status":"ok"}\n', '"status": "ok"',
    )
    assert not ValidateServiceTool._response_contains(
        "HelloAlice", "Hello Alice",
    )


def test_edit_refreshes_workspace_before_materializing_regression():
    order = []
    session = SimpleNamespace(
        invalidate=lambda path: order.append(("invalidate", path)),
        refresh=lambda: order.append(("refresh", None)),
    )
    agent = SimpleNamespace(
        validation_pipeline=SimpleNamespace(
            record_edit=lambda: 1,
            state=SimpleNamespace(plan=SimpleNamespace(checks=())),
        ),
        sync_requirements_state=lambda: None,
        working_summary=SimpleNamespace(
            advance_revision=lambda revision: None,
            memory=None,
        ),
        workspace_session=session,
        materialize_regression_checks=lambda path: order.append(
            ("materialize", path)
        ),
        progress=SimpleNamespace(mark_meaningful_progress=lambda: None),
        plan_orchestrator=SimpleNamespace(reconcile=lambda current: (None, ())),
        _repo_map_initialized=True,
        _repo_map_revision=1,
    )

    EditResultHandler().apply(
        agent,
        tool_name="write_file",
        arguments={"path": "package.json"},
        result=ToolResult(True, "edited", {}),
        current_plan_step=None,
        emit=lambda *args, **kwargs: None,
    )

    assert order == [
        ("invalidate", "package.json"),
        ("refresh", None),
        ("materialize", "package.json"),
    ]


def test_pytest_no_tests_collected_is_inconclusive_not_failure():
    pipeline = planned(TestTargetContract("health.py"))
    resolution = ValidatorResolution(
        "V1", ResolutionStatus.RESOLVED, "run_tests", {},
        "test.run", "health.py", "pytest|health.py",
    )
    evidence = pipeline.observe("run_tests", {"path": "health.py", "purpose": "acceptance"},
                                ToolResult(True, "exit 5", {
                                    "tests_passed": False, "passed": 0, "failed": 0,
                                    "errors": 0, "exit_code": 5,
                                }), resolution=resolution)
    assert evidence.outcome == ValidationOutcome.INCONCLUSIVE
    assert pipeline.state.proof("V1") is None


def _metric_evidence(check_id, outcome):
    return ValidationEvidence(
        "run_tests", True, outcome, ValidationScope.TARGETED,
        ValidationPurpose.ACCEPTANCE, 1, check_id=check_id,
        requirement_ids=(check_id.replace("V", "R"),),
    )


def test_first_pass_requires_all_acceptance_checks_first_executions_to_pass():
    plan = SimpleNamespace(checks=(
        SimpleNamespace(id="V1", required=True, purpose=ValidationPurpose.ACCEPTANCE),
        SimpleNamespace(id="V2", required=True, purpose=ValidationPurpose.ACCEPTANCE),
    ))
    common = dict(
        edit_count=1, edit_revision=1, acceptance_passed=True, plan=plan,
        recovery_entered=False, corrective_edit=False, repair_attempts=0,
        rollback_count=0, oracle_passed=True,
    )
    assert EvaluationHarness._first_pass_success(
        **common,
        evidence_history=[
            _metric_evidence("V1", ValidationOutcome.PASSED),
            _metric_evidence("V2", ValidationOutcome.PASSED),
        ],
    )
    assert not EvaluationHarness._first_pass_success(
        **common,
        evidence_history=[
            _metric_evidence("V1", ValidationOutcome.PASSED),
            _metric_evidence("V2", ValidationOutcome.FAILED),
            _metric_evidence("V2", ValidationOutcome.PASSED),
        ],
    )


def test_first_pass_cannot_be_true_when_acceptance_is_false():
    plan = SimpleNamespace(checks=(
        SimpleNamespace(id="V1", required=True, purpose=ValidationPurpose.ACCEPTANCE),
    ))
    assert not EvaluationHarness._first_pass_success(
        edit_count=1, edit_revision=1, acceptance_passed=False, plan=plan,
        evidence_history=[_metric_evidence("V1", ValidationOutcome.PASSED)],
        recovery_entered=False, corrective_edit=False, repair_attempts=0,
        rollback_count=0, oracle_passed=True,
    )


def test_python_behavior_command_sets_src_layout_pythonpath(tmp_path):
    contract = PythonBehaviorContract("from calculator import add; assert add(1, 2) == 3")
    check = ValidationPlanner().build(requirements(contract)).checks[0]
    registry = ToolRegistry()
    registry.register(CommandTool())
    resolution = ValidatorResolver(tmp_path).resolve(check, registry=registry)
    assert resolution.status == ResolutionStatus.RESOLVED
    command = resolution.arguments["command"]
    assert "PYTHONPATH=" in command
    assert str((tmp_path / "src").resolve()) in command
    assert str(tmp_path.resolve()) in command


def test_python_behavior_resolves_src_layout_without_cd(tmp_path):
    src_pkg = tmp_path / "src" / "calculator"
    src_pkg.mkdir(parents=True)
    (src_pkg / "__init__.py").write_text("from .service import add\n", encoding="utf-8")
    (src_pkg / "service.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    contract = PythonBehaviorContract(
        "from calculator import add; assert add(1, 2) == 3"
    )
    check = ValidationPlanner().build(requirements(contract)).checks[0]
    registry = ToolRegistry()
    registry.register(RunCommandTool(tmp_path))
    resolution = ValidatorResolver(tmp_path).resolve(check, registry=registry)
    assert resolution.status == ResolutionStatus.RESOLVED
    assert "cd " not in resolution.arguments["command"]
    result = RunCommandTool(tmp_path).execute(
        resolution.arguments["command"], purpose="acceptance",
    )
    assert result.data["command_succeeded"] is True
    assert result.data["exit_code"] == 0


def test_node_behavior_uses_repository_runtime_without_oracle_rewrite(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "range.ts").write_text(
        "export function inclusiveRange(start: number, end: number): number[] {\n"
        "  const out = [];\n"
        "  for (let i = start; i <= end; i++) out.push(i);\n"
        "  return out;\n"
        "}\n",
        encoding="utf-8",
    )
    contract = NodeBehaviorContract(
        "import { inclusiveRange } from './src/range.ts';\n"
        "if (JSON.stringify(inclusiveRange(2, 4)) !== '[2,3,4]') process.exit(2);\n"
    )
    check = ValidationPlanner().build(requirements(contract)).checks[0]
    registry = ToolRegistry()
    registry.register(RunCommandTool(tmp_path))
    resolution = ValidatorResolver(tmp_path).resolve(check, registry=registry)
    command = resolution.arguments["command"]
    assert "data:text/javascript;base64" not in command
    assert "inclusiveRange" in command


def test_browser_node_fallback_accepts_standard_onclick_handler(tmp_path):
    completed = _execute_browser_fallback(
        tmp_path,
        """\
<button id="move">Move</button>
<div id="state">idle</div>
<script type="module" src="./app.js"></script>
""",
        """\
document.getElementById("move").onclick = () => {
  document.getElementById("state").textContent = "moved";
};
""",
        BrowserAction("click", "#move"),
        BrowserAssertion("text_equals", "#state", "moved"),
    )
    assert completed.returncode == 0, completed.stderr
