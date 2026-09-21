from types import SimpleNamespace
from pathlib import Path

import pytest

from ..main import build_agent
from ..workspace import WorkspaceConfig
from ..agent.planning.requirements import RequirementCategory, TaskRequirement, TaskRequirements
from ..agent.validation import (
    BrowserAction, BrowserAssertion, BrowserInteractionContract, HttpContract,
    SemanticContract, TestTargetContract,
)
from ..agent.validation.plan import EvidenceStrength, ValidationCheck, ValidationPlanner
from ..agent.validation.pipeline import ValidationPipeline
from ..agent.validation.evidence import ValidationPurpose
from ..agent.validation.validator_resolver import ResolutionStatus, ValidatorResolver
from ..agent.validation.executor import ValidationExecutionState, ValidationExecutor
from ..agent.validation.validator_resolver import ValidatorResolution
from ..evaluation.real_repo_bench import fixtures, run_real_repo_bench
from ..evaluation.checks import EvaluationCheckRunner
from ..evaluation.models import EvaluationCheck
from ..tools.registry import ToolRegistry
from ..tools.validation.validate_semantic import ValidateSemanticTool
from ..agent.context import ProjectExecutionEnvironment
from ..tools.execution import RunTestsTool
from ..agent.safety import SafetyPolicy
from ..agent.runtime.tool_executor import ToolExecutor
from ..agent.progress import ActionController
from ..agent.routing import ExecutionMode, policy_for
from ..agent.task_state import AgentPhase, TaskState


def test_workspace_config_defaults_to_current_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    config = WorkspaceConfig.create()
    assert config.workspace_root == tmp_path.resolve()
    assert config.runtime_root == Path.home() / ".minicodex" / "workspaces" / config.repository_key
    assert config.repository_key.startswith(f"{tmp_path.name}-")


def test_workspace_config_rejects_missing_or_file(tmp_path):
    with pytest.raises(ValueError, match="不存在"):
        WorkspaceConfig.create(tmp_path / "missing")
    file = tmp_path / "file.txt"
    file.write_text("x")
    with pytest.raises(ValueError, match="不是目录"):
        WorkspaceConfig.create(file)


def test_composition_root_propagates_external_workspace(tmp_path):
    config = WorkspaceConfig.create(tmp_path)
    agent, _trace, memory = build_agent(config, llm=SimpleNamespace(), control_llm=SimpleNamespace(), judge_llm=SimpleNamespace())
    assert agent.workspace == tmp_path.resolve()
    assert memory.repository_key == config.repository_key
    assert all(getattr(tool, "workspace", tmp_path.resolve()) == tmp_path.resolve()
               for tool in agent.registry._tools.values() if hasattr(tool, "workspace"))


def test_required_runtime_check_survives_missing_browser_capability():
    requirements = TaskRequirements([TaskRequirement("R1", "ArrowLeft moves block", RequirementCategory.BEHAVIOR,
        paths=("game.html",), contract=BrowserInteractionContract(
            "game.html", BrowserAction("keypress", value="ArrowLeft"),
            BrowserAssertion("text_equals", "#state", "left"),
        ))])
    profile = SimpleNamespace(commands=())
    plan = ValidationPlanner().build(requirements, profile=profile, paths=("game.html",),
        request="Create a playable game with ArrowLeft interaction", available_capabilities=frozenset())
    runtime = next(check for check in plan.checks if check.strength == EvidenceStrength.RUNTIME)
    assert runtime.required and runtime.contract_type == "browser_interaction"
    resolved = ValidatorResolver().resolve(runtime, registry=ToolRegistry(), profile=profile, paths=("game.html",))
    assert resolved.status == ResolutionStatus.CAPABILITY_MISSING


def test_optional_semantic_validator_allows_bound_provider_evidence():
    """Fallback semantic checks must not deadlock without an optional judge."""

    requirements = TaskRequirements([
        TaskRequirement(
            "R1",
            "set VALUE to 2",
            paths=("value.py",),
            contract=SemanticContract("value.py", "set VALUE to 2"),
        )
    ])
    pipeline = ValidationPipeline()
    pipeline.state.plan = ValidationPlanner().build(requirements)
    check = pipeline.state.plan.checks[0]
    resolution = ValidatorResolution(
        check.id,
        ResolutionStatus.CAPABILITY_MISSING,
        capability="validation.semantic",
        reason="semantic validator unavailable",
    )

    result = ValidationExecutor().execute(
        SimpleNamespace(validation_pipeline=pipeline),
        check,
        resolution,
    )

    assert result.state == ValidationExecutionState.SKIPPED
    assert not pipeline.state.blocked_checks


def test_typed_http_and_browser_specs_do_not_copy_observable_to_tool_arguments(tmp_path):
    class ServiceTool:
        name = "service"
        capabilities = frozenset({"service.validate"})
    class BrowserTool:
        name = "browser"
        capabilities = frozenset({"validation.browser"})
    registry = ToolRegistry()
    registry.register(ServiceTool())
    registry.register(BrowserTool())
    profile = SimpleNamespace(commands=(("start", "python app.py {port}"),))
    http = ValidationCheck("V1", ("R1",), ValidationPurpose.ACCEPTANCE,
        HttpContract("POST", "/login", 401, json_body={"username": "demo", "password": "wrong"}),
        strength=EvidenceStrength.RUNTIME)
    http_resolution = ValidatorResolver(tmp_path).resolve(http, registry=registry, profile=profile)
    assert http_resolution.status == ResolutionStatus.RESOLVED
    assert http_resolution.arguments["method"] == "POST"
    assert http_resolution.arguments["expected_status"] == 401
    assert http_resolution.arguments["json_body"] == {"username": "demo", "password": "wrong"}
    assert "do not pass" not in str(http_resolution.arguments)
    browser = ValidationCheck("V2", ("R2",), ValidationPurpose.ACCEPTANCE,
        BrowserInteractionContract(
            "game.html", BrowserAction("keypress", "#board", "ArrowLeft"),
            BrowserAssertion("text_equals", "#board", "moved"),
        ), strength=EvidenceStrength.RUNTIME)
    browser_resolution = ValidatorResolver(tmp_path).resolve(browser, registry=registry, profile=profile)
    assert browser_resolution.arguments["keypress"] == "ArrowLeft"
    assert browser_resolution.arguments["expected_text"] == "moved"


def test_real_repo_bench_is_opt_in_and_has_realistic_families(tmp_path):
    assert len(fixtures()) >= 20
    assert {tag for fixture in fixtures() for tag in fixture.case.tags} >= {"python", "fastapi", "web", "typescript"}
    with pytest.raises(ValueError, match="opt-in"):
        run_real_repo_bench(tmp_path, model_factory=None)


def test_semantic_validation_is_read_only_and_deterministic_when_claim_is_literal(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("Token expiry is 15 minutes.")
    tool = ValidateSemanticTool(tmp_path)
    result = tool.execute("README.md", "Token expiry is 15 minutes.")
    assert result.data["outcome"] == "passed"
    assert readme.read_text() == "Token expiry is 15 minutes."


def test_target_project_virtualenv_is_preferred_for_test_execution(tmp_path):
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    environment = ProjectExecutionEnvironment.discover(tmp_path)
    assert environment.python_executable == str(python)
    assert RunTestsTool(workspace=tmp_path).python_executable == str(python)


def test_project_execution_environment_uses_available_uv_command(monkeypatch, tmp_path):
    (tmp_path / "uv.lock").write_text("")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/uv" if name == "uv" else None)
    environment = ProjectExecutionEnvironment.discover(tmp_path)
    assert environment.command_available
    assert environment.pytest_argv("tests/test_app.py") == ("uv", "run", "pytest", "tests/test_app.py")


def test_project_execution_environment_reports_missing_poetry(monkeypatch, tmp_path):
    (tmp_path / "poetry.lock").write_text("")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    environment = ProjectExecutionEnvironment.discover(tmp_path)
    assert not environment.command_available


def test_independent_python_oracle_does_not_pass_for_existing_wrong_file(tmp_path):
    target = tmp_path / "src" / "pkg" / "maths.py"
    target.parent.mkdir(parents=True)
    target.write_text("def double(value): return value + 2\n")
    check = EvaluationCheck("python_assertion", command="from pkg.maths import double; assert double(3) == 6")
    assert not EvaluationCheckRunner().run(check=check, workspace=tmp_path, output="Task completed successfully.").passed
    target.write_text("def double(value): return value * 2\n")
    assert EvaluationCheckRunner().run(check=check, workspace=tmp_path, output="false positive irrelevant").passed


def test_hidden_pytest_oracle_runs_outside_agent_workspace(tmp_path):
    workspace = tmp_path / "workspace"; oracle = tmp_path / "oracle"
    (workspace / "src" / "pkg").mkdir(parents=True); oracle.mkdir()
    (workspace / "src" / "pkg" / "value.py").write_text("def answer(): return 42\n")
    (oracle / "test_value.py").write_text("from pkg.value import answer\ndef test_answer(): assert answer() == 42\n")
    check = EvaluationCheck("pytest_passes", path="test_value.py")
    result = EvaluationCheckRunner().run(check=check, workspace=workspace, oracle_root=oracle, output="")
    assert result.passed
    assert not (workspace / "test_value.py").exists()


def test_runtime_directory_is_not_an_ordinary_edit_target(tmp_path):
    decision = SafetyPolicy(workspace=tmp_path).assess("write_file", {"path": ".minicodex/traces/latest.jsonl"})
    assert not decision.allowed


def test_tool_executor_rejects_oversized_or_unknown_arguments(tmp_path):
    registry = ToolRegistry()
    registry.register(ValidateSemanticTool(tmp_path))
    executor = ToolExecutor(registry)
    assert executor.prepare("validate_semantic", "{" + "x" * executor.MAX_TOOL_ARGUMENT_CHARS + "}").error
    assert executor.prepare("validate_semantic", '{"path":"README.md","claim":"x","unexpected":true}').error


def test_bound_test_spec_is_executed_exactly_and_stale_target_is_unresolved(tmp_path):
    test = tmp_path / "tests" / "test_auth.py"
    test.parent.mkdir()
    test.write_text("def test_invalid_password(): pass\n")
    class Tests:
        name = "tests"
        capabilities = frozenset({"test.run"})
    registry = ToolRegistry(); registry.register(Tests())
    check = ValidationCheck("V1", ("R1",), ValidationPurpose.ACCEPTANCE,
        TestTargetContract("tests/test_auth.py::test_invalid_password"))
    resolved = ValidatorResolver(tmp_path).resolve(check, registry=registry)
    assert resolved.status == ResolutionStatus.RESOLVED
    assert resolved.arguments["path"] == "tests/test_auth.py::test_invalid_password"
    test.unlink()
    assert ValidatorResolver(tmp_path).resolve(check, registry=registry).status == ResolutionStatus.TARGET_UNRESOLVED


def test_unresolved_validation_allows_one_relevant_read_but_resolved_does_not():
    class Read:
        name = "read_file"
        capabilities = frozenset({"filesystem.read"})
    registry = ToolRegistry(); registry.register(Read())
    controller = ActionController(registry)
    policy = policy_for(ExecutionMode.STANDARD)
    state = TaskState(phase=AgentPhase.VALIDATING, relevant_paths=("app/routes.py",))
    controller.update_context(state=state, policy=policy, remaining_budget=5,
        next_required_check_id="V1", validator_resolution_status="target_unresolved",
        validation_paths=("app/routes.py",))
    assert controller.restriction_reason("read_file", {"path": "app/routes.py"}, policy) is None
    assert controller.restriction_reason("read_file", {"path": "app/routes.py"}, policy)
    controller.update_context(state=state, policy=policy, remaining_budget=5,
        next_required_check_id="V1", validator_resolution_status="resolved")
    assert controller.restriction_reason("read_file", {"path": "app/routes.py"}, policy)


def test_browser_runtime_spec_requires_post_action_assertion(tmp_path):
    class Browser:
        name = "browser"
        capabilities = frozenset({"validation.browser"})
    registry = ToolRegistry(); registry.register(Browser())
    check = ValidationCheck("V1", ("R1",), ValidationPurpose.ACCEPTANCE,
        BrowserInteractionContract(
            "index.html", BrowserAction("click", "#move"),
            BrowserAssertion("text_equals", "", ""),
        ))
    assert ValidatorResolver(tmp_path).resolve(check, registry=registry).status == ResolutionStatus.TARGET_UNRESOLVED


def test_auth_http_contract_without_json_body_is_unresolved(tmp_path):
    registry = ToolRegistry()
    registry.register(type("Service", (), {
        "name": "service", "capabilities": frozenset({"service.validate"}),
    })())
    profile = SimpleNamespace(commands=(("start", "python app.py {port}"),))
    check = ValidationCheck(
        "V1", ("R1",), ValidationPurpose.ACCEPTANCE,
        HttpContract("POST", "/login", 200),
    )
    resolution = ValidatorResolver(tmp_path).resolve(check, registry=registry, profile=profile)
    assert resolution.status == ResolutionStatus.TARGET_UNRESOLVED
    assert "json_body" in resolution.reason


def test_auth_http_contract_with_json_body_resolves_inprocess(tmp_path):
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )
    registry = ToolRegistry()
    registry.register(type("Run", (), {
        "name": "run_command", "capabilities": frozenset({"process.run"}),
    })())
    check = ValidationCheck(
        "V1", ("R1",), ValidationPurpose.ACCEPTANCE,
        HttpContract(
            "POST", "/login", 200,
            expected_text="token",
            json_body={"username": "demo", "password": "demo"},
        ),
    )
    resolution = ValidatorResolver(tmp_path).resolve(check, registry=registry)
    assert resolution.status == ResolutionStatus.RESOLVED
    command = resolution.arguments["command"]
    assert "username" in command and "demo" in command and "password" in command
    assert "json=None" not in command
    assert "token" in command
    assert "r.text" in command


def test_http_status_binding_accepts_normal_success_and_conflict_codes(tmp_path):
    profile = SimpleNamespace(commands=(("start", "python app.py {port}"),))
    for status in (200, 201, 204, 409, 422):
        contract = HttpContract("POST", "/items", status)
        check = ValidationCheck("V1", ("R1",), ValidationPurpose.ACCEPTANCE, contract)
        registry = ToolRegistry()
        registry.register(type("Service", (), {"name": "service", "capabilities": frozenset({"service.validate"})})())
        assert ValidatorResolver(tmp_path).resolve(check, registry=registry, profile=profile).arguments["expected_status"] == status
