from types import SimpleNamespace

import pytest

from ..main import build_agent
from ..workspace import WorkspaceConfig
from ..agent.planning.requirements import RequirementCategory, TaskRequirement, TaskRequirements
from ..agent.validation import BrowserVerificationSpec, HttpVerificationSpec
from ..agent.validation.plan import EvidenceStrength, ValidationCheck, ValidationPlanner
from ..agent.validation.evidence import ValidationPurpose
from ..agent.validation.validator_resolver import ResolutionStatus, ValidatorResolver
from ..evaluation.real_repo_bench import fixtures, run_real_repo_bench
from ..evaluation.checks import EvaluationCheckRunner
from ..evaluation.models import EvaluationCheck
from ..tools.registry import ToolRegistry
from ..tools.validation.validate_semantic import ValidateSemanticTool
from ..agent.context import ProjectExecutionEnvironment
from ..tools.execution import RunTestsTool
from ..agent.safety import SafetyPolicy
from ..agent.validation import VerificationSpecBinder
from ..agent.context.workspace_session import WorkspaceSession
from ..agent.runtime.tool_executor import ToolExecutor


def test_workspace_config_defaults_to_current_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    config = WorkspaceConfig.create()
    assert config.workspace_root == tmp_path.resolve()
    assert config.runtime_root == tmp_path / ".minicodex"
    assert config.repository_key.startswith(f"{tmp_path.name}-")


def test_workspace_config_rejects_missing_or_file(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        WorkspaceConfig.create(tmp_path / "missing")
    file = tmp_path / "file.txt"
    file.write_text("x")
    with pytest.raises(ValueError, match="not a directory"):
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
        paths=("game.html",), observable="keypress ArrowLeft moves block left")])
    profile = SimpleNamespace(commands=())
    plan = ValidationPlanner().build(requirements, profile=profile, paths=("game.html",),
        request="Create a playable game with ArrowLeft interaction", available_capabilities=frozenset())
    runtime = next(check for check in plan.checks if check.strength == EvidenceStrength.RUNTIME)
    assert runtime.required and runtime.capability == "validation.browser"
    resolved = ValidatorResolver().resolve(runtime, registry=ToolRegistry(), profile=profile, paths=("game.html",))
    assert resolved.status == ResolutionStatus.CAPABILITY_MISSING


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
    http = ValidationCheck("V1", ("R1",), ValidationPurpose.ACCEPTANCE, capability="service.validate",
        strength=EvidenceStrength.RUNTIME, observable="do not pass this prose", spec=HttpVerificationSpec("POST", "/login", 401))
    http_resolution = ValidatorResolver(tmp_path).resolve(http, registry=registry, profile=profile)
    assert http_resolution.status == ResolutionStatus.RESOLVED
    assert http_resolution.arguments["method"] == "POST"
    assert http_resolution.arguments["expected_status"] == 401
    assert "do not pass" not in str(http_resolution.arguments)
    browser = ValidationCheck("V2", ("R2",), ValidationPurpose.ACCEPTANCE, capability="validation.browser",
        strength=EvidenceStrength.RUNTIME, observable="untrusted prose", spec=BrowserVerificationSpec(
            "game.html", "#board", "keypress", "ArrowLeft", "moved"))
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


def test_independent_python_oracle_does_not_pass_for_existing_wrong_file(tmp_path):
    target = tmp_path / "src" / "pkg" / "maths.py"
    target.parent.mkdir(parents=True)
    target.write_text("def double(value): return value + 2\n")
    check = EvaluationCheck("python_assertion", command="from pkg.maths import double; assert double(3) == 6")
    assert not EvaluationCheckRunner().run(check=check, workspace=tmp_path, output="Task completed successfully.").passed
    target.write_text("def double(value): return value * 2\n")
    assert EvaluationCheckRunner().run(check=check, workspace=tmp_path, output="false positive irrelevant").passed


def test_runtime_directory_is_not_an_ordinary_edit_target(tmp_path):
    decision = SafetyPolicy(workspace=tmp_path).assess("write_file", {"path": ".minicodex/traces/latest.jsonl"})
    assert not decision.allowed


def test_browser_spec_is_bound_only_after_inspected_dom_facts_are_available(tmp_path):
    (tmp_path / "index.html").write_text("<div id='state'>idle</div><script>document.onkeydown = () => {}</script>")
    session = WorkspaceSession(tmp_path)
    session.refresh()
    requirement = TaskRequirement("R1", "left movement", RequirementCategory.BEHAVIOR,
        paths=("index.html",), observable="Pressing ArrowLeft moves the active piece left.")
    check = ValidationCheck("V1", ("R1",), ValidationPurpose.ACCEPTANCE, capability="validation.browser",
        strength=EvidenceStrength.RUNTIME)
    bound = VerificationSpecBinder().bind(check, requirement, session=session).check.spec
    assert isinstance(bound, BrowserVerificationSpec)
    assert bound.expected_text == "left"


def test_http_binder_ranks_login_route_above_unrelated_health_route(tmp_path):
    (tmp_path / "routes.py").write_text("@app.get('/health')\ndef health(): return {}\n@app.post('/login')\ndef login(): return {}\n")
    session = WorkspaceSession(tmp_path)
    session.refresh()
    requirement = TaskRequirement("R1", "invalid login", RequirementCategory.BEHAVIOR,
        paths=("routes.py",), observable="invalid login password returns 401")
    check = ValidationCheck("V1", ("R1",), ValidationPurpose.ACCEPTANCE, capability="service.validate")
    result = VerificationSpecBinder().bind(check, requirement, session=session)
    assert isinstance(result.check.spec, HttpVerificationSpec)
    assert result.check.spec.path == "/login"
    assert result.check.spec_bound_revision == session.revision


def test_tool_executor_rejects_oversized_or_unknown_arguments(tmp_path):
    registry = ToolRegistry()
    registry.register(ValidateSemanticTool(tmp_path))
    executor = ToolExecutor(registry)
    assert executor.prepare("validate_semantic", "{" + "x" * executor.MAX_TOOL_ARGUMENT_CHARS + "}").error
    assert executor.prepare("validate_semantic", '{"path":"README.md","claim":"x","unexpected":true}').error
