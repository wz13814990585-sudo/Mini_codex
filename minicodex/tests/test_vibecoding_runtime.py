"""Executable regression scenarios for requirement-driven coding."""
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import socket
import sys
import threading

import pytest

from minicodex.agent.context.workspace_session import WorkspaceSession, ChangeImpactResolver
from minicodex.agent.editing.edit_intent import EditIntent, DiffQualityGate, verify_edit_intent
from minicodex.agent.editing.edit_verifier import DEFER_SYNTAX, EditVerifier
from minicodex.agent.editing.checkpoint import CheckpointManager
from minicodex.agent.editing.rollback import RollbackEngine
from minicodex.agent.editing.work_unit import WorkUnit, WorkUnitStatus
from minicodex.agent.planning.requirements import TaskRequirement, TaskRequirements, RequirementCategory
from minicodex.agent.runtime.managed_process import ManagedProcess
from minicodex.agent.task_state import TaskRuntime, TaskState, RuntimeEvent, RuntimeEventType, reduce_task_state
from minicodex.agent.validation.contracts import (
    HttpContract, SemanticContract, TestTargetContract,
)
from minicodex.agent.validation.plan import ValidationPlanner
from minicodex.agent.validation.pipeline import ValidationPipeline
from minicodex.agent.validation.evidence import ValidationOutcome
from minicodex.agent.validation.plan import EvidenceStrength
from minicodex.agent.validation.regression_policy import RegressionPolicy, RegressionRequirement
from minicodex.agent.validation.validator_resolver import (
    ResolutionStatus, ValidatorResolution,
)
from minicodex.tools.registry import ToolRegistry
from minicodex.tools.results import ToolResult


def setup_requirements(*categories):
    requirements = TaskRequirements([TaskRequirement(
        f"R{i}", f"outcome {i}", category,
        contract=SemanticContract(f"file{i}.md", f"outcome {i}"),
    )
                                    for i, category in enumerate(categories or [RequirementCategory.BEHAVIOR] * 2, 1)])
    pipeline = ValidationPipeline()
    pipeline.state.plan = ValidationPlanner().build(requirements)
    return requirements, pipeline


def observe(pipeline, check="V1", path="tests/test_x.py::test_one", passed=True, **kwargs):
    return pipeline.observe("run_tests", {"path": path, "purpose": "acceptance", "validation_check": check},
                            ToolResult(True, "fixture", {"tests_passed": passed, "passed": int(passed),
                            "failed": int(not passed), "errors": 0, "skipped": 0, **kwargs}),
                            resolution=ValidatorResolution(
                                check, ResolutionStatus.RESOLVED, "run_tests",
                                {"path": path}, "test.run", path, f"pytest|{path}",
                            ))


def satisfied_ids(requirements, pipeline):
    return {
        requirement.id for requirement in requirements.items
        if all(pipeline.state.proof(check.id) for check in pipeline.state.plan.for_requirement(requirement.id))
    }


def test_one_check_cannot_satisfy_another_requirement():
    requirements, pipeline = setup_requirements()
    observe(pipeline)
    assert satisfied_ids(requirements, pipeline) == {"R1"}
    from minicodex.agent.validation.decision_policy import ValidationDecisionPolicy
    assert ValidationDecisionPolicy(pipeline.state).next_action().value == "run_check"
    assert ValidationDecisionPolicy(pipeline.state).next_required_check().id == "V2"


def test_two_independent_checks_required_and_current():
    requirements, pipeline = setup_requirements()
    observe(pipeline)
    observe(pipeline, "V2", "tests/test_x.py::test_two", False)
    assert satisfied_ids(requirements, pipeline) == {"R1"}
    for _ in range(3):
        observe(pipeline, "V2", "tests/test_x.py::test_two")
    assert satisfied_ids(requirements, pipeline) == {"R1"}
    pipeline.record_edit()
    assert not satisfied_ids(requirements, pipeline)


def test_explicit_check_bindings_can_share_one_test_target():
    requirements, pipeline = setup_requirements()
    observe(pipeline)
    observe(pipeline, "V2")
    assert satisfied_ids(requirements, pipeline) == {"R1", "R2"}


def test_agent_created_test_alone_cannot_establish_requirement():
    _, pipeline = setup_requirements()
    observe(pipeline, agent_test_only=True)
    assert pipeline.state.proof("V1") is None


@pytest.mark.parametrize("category", [RequirementCategory.FILE, RequirementCategory.DOCUMENTATION, RequirementCategory.TEST])
def test_edit_is_not_requirement_evidence(category):
    requirements, pipeline = setup_requirements(category)
    pipeline.record_edit()
    assert not satisfied_ids(requirements, pipeline)


def test_true_contradiction_remains_unstable_for_revision():
    _, pipeline = setup_requirements()
    assert not observe(pipeline).unstable
    assert observe(pipeline, passed=False).unstable
    assert observe(pipeline).unstable
    assert observe(pipeline).unstable
    assert observe(pipeline).unstable


def test_static_html_does_not_prove_game_behavior():
    _, pipeline = setup_requirements(RequirementCategory.BEHAVIOR)
    pipeline.observe("validate_static_web", {"path": "game.html"}, ToolResult(True, "ok", {"outcome": "passed"}))
    assert pipeline.state.proof("V1") is None


def test_check_cannot_switch_target_after_first_execution():
    _, pipeline = setup_requirements()
    observe(pipeline, passed=False)
    observe(pipeline, path="tests/test_unrelated.py::test_green")
    assert pipeline.state.proof("V1") is None


def test_independent_api_requests_to_same_path_have_distinct_checks():
    _, pipeline = setup_requirements()
    for check, body, status in (("V1", {"password": "wrong"}, 401), ("V2", {"password": "valid"}, 200)):
        pipeline.observe("validate_service", {"path": "/login", "method": "POST", "json_body": body,
                         "expected_status": status, "validation_check": check},
                         ToolResult(True, "asserted", {"outcome": "passed"}),
                         capabilities=frozenset({"service.validate"}),
                         resolution=ValidatorResolution(
                             check, ResolutionStatus.RESOLVED, "validate_service",
                             {}, "service.validate", f"POST /login {status}",
                             f"http|{body}|{status}",
                         ))
    assert pipeline.state.proof("V1") and pipeline.state.proof("V2")


def test_weak_check_does_not_lock_out_stronger_evidence():
    _, pipeline = setup_requirements(RequirementCategory.BEHAVIOR)
    pipeline.observe("validate_static_web", {"path": "game.html"}, ToolResult(True, "syntax", {"outcome": "passed"}))
    pipeline.observe("validate_browser_app", {"path": "game.html", "keypress": "ArrowDown", "expected_text": "Score: 1"},
                     ToolResult(True, "behavior", {"outcome": "passed", "evidence_strength": 5}))
    assert pipeline.state.proof("V1") is None


@pytest.mark.parametrize("command", ["echo tests passed", "echo assert", "python -c 'assert True'",
                                      "python -O -c 'assert actual == expected'", "curl http://localhost:8000"])
def test_command_exit_zero_alone_is_not_behavioral_evidence(command):
    _, pipeline = setup_requirements(RequirementCategory.BEHAVIOR)
    pipeline.observe("run_command", {"command": command, "purpose": "acceptance"},
                     ToolResult(True, "exit zero", {"command_succeeded": True}))
    assert pipeline.state.proof("V1") is None


def test_revision_changing_validator_requires_a_fresh_check():
    _, pipeline = setup_requirements(RequirementCategory.BEHAVIOR)
    command = "python -c 'assert actual == expected'"
    args = {"command": command, "purpose": "acceptance"}
    evidence = pipeline.observe("run_command", args, ToolResult(True, "executed", {
        "command_succeeded": True, "workspace_changed_during_validation": True}))
    assert evidence is None
    assert pipeline.state.proof("V1") is None


def test_workunit_allows_temporary_syntax_but_is_bounded():
    unit = WorkUnit("W1", (), ("a.py", "b.py"), 0, edit_budget=2)
    token = DEFER_SYNTAX.set(unit.permits_intermediate_syntax)
    try:
        assert not EditVerifier.validate_candidate(Path("a.py"), "def x(")
    finally:
        DEFER_SYNTAX.reset(token)
    with pytest.raises(ValueError):
        EditVerifier.validate_candidate(Path("a.py"), "def x(")
    unit = unit.record_edit("a.py").record_edit("b.py")
    assert unit.milestone_due and not unit.permits_intermediate_syntax


def test_single_file_edit_does_not_defer_syntax():
    assert not WorkUnit("W1", (), ("a.py",), 0).permits_intermediate_syntax


def test_workunit_closes_only_after_its_milestone_proofs():
    state = TaskState(target_paths=("model.py", "service.py"), requirement_ids=("R1",))
    state = reduce_task_state(state, RuntimeEvent.create(RuntimeEventType.EDIT_APPLIED,
        edit_revision=1, path="model.py", milestone_check_ids=("V1",)))
    assert state.work_unit.status == WorkUnitStatus.OPEN
    state = reduce_task_state(state, RuntimeEvent.create(RuntimeEventType.VALIDATION_OBSERVED,
        outcome=ValidationOutcome.PASSED, workunit_all_milestones_resolved=None))
    assert state.work_unit.status == WorkUnitStatus.VALIDATING
    state = reduce_task_state(state, RuntimeEvent.create(RuntimeEventType.VALIDATION_OBSERVED,
        outcome=ValidationOutcome.PASSED, workunit_all_milestones_resolved=True))
    assert state.work_unit.status == WorkUnitStatus.COMPLETED


def test_python_profile_and_conventions(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["pytest", "fastapi"]\n[tool.ruff]\n')
    (tmp_path / "app.py").write_text("async def run() -> int:\n    return 1\n")
    session = WorkspaceSession(tmp_path)
    session.refresh()
    assert session.profile.languages == ("Python",)
    assert session.profile.test_framework == "pytest"
    assert "fastapi" in session.profile.frameworks
    assert "async functions present" in session.conventions.observations


def test_js_profile_and_commands(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies":{"react":"*"},"devDependencies":{"vitest":"*"},"scripts":{"test":"vitest","build":"vite build"}}')
    (tmp_path / "app.ts").write_text("export const value = 1;")
    session = WorkspaceSession(tmp_path)
    session.refresh()
    assert session.profile.test_framework == "vitest"
    assert dict(session.profile.commands)["build"] == "npm run build"


def test_ladder_turns_required_rungs_into_plan_checks(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["pytest", "fastapi"]\n[tool.ruff]\n')
    (tmp_path / "auth.py").write_text("def login(): pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth.py").write_text("def test_login(): pass\n")
    session = WorkspaceSession(tmp_path)
    session.refresh()
    requirements = TaskRequirements([TaskRequirement(
        "R1", "invalid login", paths=("auth.py",),
        contract=HttpContract("POST", "/login", 401),
    )])
    plan = ValidationPlanner().build(requirements, profile=session.profile, paths=("auth.py",), request="Fix auth API login")
    assert [check.strength for check in plan.checks] == [EvidenceStrength.RUNTIME]
    readme = ValidationPlanner().build(TaskRequirements([TaskRequirement(
        "R1", "update README", RequirementCategory.DOCUMENTATION,
        paths=("README.md",), contract=SemanticContract("README.md", "README explains token expiry"),
    )]), profile=session.profile,
        paths=("README.md",), request="Document token expiry")
    assert [check.strength for check in readme.checks] == [EvidenceStrength.TARGETED]
    assert readme.checks[0].contract_type == "semantic"


def test_session_reuses_knowledge_but_invalidates_external_changes(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    session = WorkspaceSession(tmp_path)
    assert session.refresh()
    assert not session.refresh()
    assert session.build_count == 1
    (tmp_path / "app.py").write_text("x = 22\n")
    assert session.refresh()
    assert session.build_count == 2
    assert not any(name in vars(session) for name in ("requirements", "plan", "validation", "blocker", "recovery"))


def test_session_skips_full_scan_on_unchanged_periodic_turn(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    session = WorkspaceSession(tmp_path)
    session.refresh(full=True)
    builds = session.build_count
    for _ in range(session.external_check_interval - 1):
        assert not session.refresh(periodic=True)
    assert session.build_count == builds


def test_navigation_is_bounded_and_finds_dependents(tmp_path):
    (tmp_path / "a.py").write_text("from b import value\n")
    (tmp_path / "b.py").write_text("value = 1\n")
    session = WorkspaceSession(tmp_path)
    session.refresh()
    impact = ChangeImpactResolver().resolve(session, ("b.py",), limit=1)
    assert impact.dependents == ("a.py",)
    assert len(impact.neighbors) <= 1


def test_nested_src_layout_imports_and_tests_are_discovered(tmp_path):
    package = tmp_path / "src" / "widgets"
    tests = package / "tests"
    tests.mkdir(parents=True)
    (package / "model.py").write_text("VALUE = 1\n")
    (package / "service.py").write_text("from . import model\n")
    (tests / "test_model.py").write_text("from widgets import model\n")
    session = WorkspaceSession(tmp_path)
    session.refresh()
    impact = ChangeImpactResolver().resolve(session, ("src/widgets/model.py",))
    assert "src/widgets/service.py" in impact.dependents
    assert impact.tests == ("src/widgets/tests/test_model.py",)
    assert session.profile.test_roots == ("src/widgets/tests",)


@pytest.mark.parametrize("manifest", ['[]', '{"dependencies":null,"scripts":null}', '{"devDependencies":42}'])
def test_incomplete_package_manifest_does_not_crash_discovery(tmp_path, manifest):
    (tmp_path / "package.json").write_text(manifest)
    session = WorkspaceSession(tmp_path)
    assert session.refresh()
    assert session.profile.package_manager == "npm"


def test_external_mutation_invalidates_task_evidence(tmp_path):
    from minicodex.agent.agent import MiniCodexAgent
    from minicodex.evaluation.vibebench import ScriptedModel
    from minicodex.tools.editing import PatchFileTool
    (tmp_path / "app.py").write_text("VALUE = 1\n")
    registry = ToolRegistry()
    registry.register(PatchFileTool(tmp_path))
    agent = MiniCodexAgent(llm=ScriptedModel(()), registry=registry, planner=None)
    agent.workspace_session.refresh()
    agent.apply_runtime_event(RuntimeEventType.TASK_STARTED, target_paths=("app.py",))
    requirements, pipeline = setup_requirements(RequirementCategory.BEHAVIOR)
    agent.task_requirements = requirements
    agent.validation_pipeline = pipeline
    observe(pipeline)
    assert satisfied_ids(requirements, pipeline) == {"R1"}
    (tmp_path / "app.py").write_text("VALUE = 22\n")
    agent.workspace_session.external_check_interval = 1
    agent.refresh_workspace_facts()
    assert pipeline.state.edit_revision == agent.task_state.edit_revision == 1
    assert pipeline.state.proof("V1") is None
    assert not satisfied_ids(requirements, pipeline) and not agent.task_state.has_edit
    agent.refresh_workspace_facts()
    assert pipeline.state.edit_revision == 1


@pytest.mark.parametrize("after,issue", [("x = 2\n", "expected_text_missing"), ("x = 1\n", "no_change")])
def test_post_edit_intent_is_independent_of_tool_success(after, issue):
    verification = verify_edit_intent(EditIntent("a.py", expected_text="x = 3"), "x = 1\n", after)
    assert not verification.passed and issue in verification.issues


def test_diff_gate_scope_size_duplicates_and_test_weakening():
    gate = DiffQualityGate()
    assert "out_of_scope" in gate.check(EditIntent("b.py", allowed_paths=("a.py",)), "x=1", "x=2")
    assert "mass_deletion" in gate.check(EditIntent("a.py"), "x=1\n" * 50, "x=2\n")
    assert "duplicate_imports" in gate.check(EditIntent("a.py"), "", "import os\nimport os\n")
    assert "assertions_removed" in gate.check(EditIntent("tests/test_a.py"), "assert True", "pass")
    assert "assertions_removed" not in gate.check(EditIntent("tests/test_a.py", allow_contract_change=True), "assert True", "pass")


def test_capability_aliases_use_same_normalization():
    for name in ("pytest_adapter", "remote_test_backend"):
        class Tool:
            capabilities = {"test.run"}
        tool = Tool()
        tool.name = name
        registry = ToolRegistry()
        registry.register(tool)
        pipeline = ValidationPipeline()
        evidence = pipeline.observe(name, {"path": "tests/test_a.py", "purpose": "acceptance"},
                                    ToolResult(True, "passed", {"tests_passed": True, "passed": 1}),
                                    capabilities=registry.capabilities_for(name))
        assert evidence.outcome.value == "passed"
        assert not registry.metadata_for(name).read_only


def test_runtime_snapshot_is_frozen_and_reducer_deterministic():
    runtime = TaskRuntime()
    before = runtime.state
    runtime.emit(RuntimeEventType.EDIT_APPLIED, path="a.py")
    assert before.edit_revision == 0 and runtime.state.edit_revision == 1
    with pytest.raises(FrozenInstanceError):
        runtime.state.edit_revision = 50
    event = RuntimeEvent.create(RuntimeEventType.TASK_STARTED, run_id="fixed")
    assert reduce_task_state(before, event) == reduce_task_state(before, event)


def test_risk_and_artifact_override_mode(tmp_path):
    policy = RegressionPolicy()
    assert policy.requirement_for(mode="fast", changed_paths=("examples/auth.py",)) == RegressionRequirement.RELEVANT_ONLY
    assert policy.requirement_for(mode="complex", changed_paths=("README.md",)) == RegressionRequirement.NOT_APPLICABLE
    session = WorkspaceSession(tmp_path)


def make_checkpoint(manager, path, content, revision):
    checkpoint = manager.capture(path=path, edit_revision=revision)
    (manager.workspace / path).write_text(content)
    manager.seal(checkpoint.checkpoint_id)


def test_undo_preserves_user_baseline(tmp_path):
    (tmp_path / "a.py").write_text("user_change = 1\n")
    manager = CheckpointManager(tmp_path)
    make_checkpoint(manager, "a.py", "agent_change = 2\n", 1)
    make_checkpoint(manager, "a.py", "agent_change = 3\n", 2)
    result = RollbackEngine(workspace=tmp_path, checkpoint_manager=manager).undo_task()
    assert result.success
    assert (tmp_path / "a.py").read_text() == "user_change = 1\n"


@pytest.mark.parametrize("between", [False, True])
def test_undo_refuses_concurrent_user_change(tmp_path, between):
    (tmp_path / "a.py").write_text("original = 1\n")
    manager = CheckpointManager(tmp_path)
    make_checkpoint(manager, "a.py", "agent = 2\n", 1)
    (tmp_path / "a.py").write_text("concurrent = 3\n")
    if between:
        make_checkpoint(manager, "a.py", "concurrent = 3\nagent = 4\n", 2)
    before = (tmp_path / "a.py").read_text()
    assert not RollbackEngine(workspace=tmp_path, checkpoint_manager=manager).undo_task().success
    assert (tmp_path / "a.py").read_text() == before


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_managed_service_ready_probe_cleanup(tmp_path):
    (tmp_path / "index.html").write_text("expected application response")
    service = ManagedProcess(tmp_path, [sys.executable, "-m", "http.server", "{port}", "--bind", "127.0.0.1"], port=free_port())
    with service:
        service.wait_ready()
        assert "expected application response" in service.probe()[1]
    assert service.process.poll() is not None


def test_service_can_assert_unauthorized_json_response(tmp_path):
    from minicodex.tools.validation.validate_service import ValidateServiceTool
    (tmp_path / "server.py").write_text(
        "import json, sys\nfrom http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_POST(self):\n"
        "        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))\n"
        "        self.send_response(401 if data['password'] == 'wrong' else 200)\n"
        "        self.end_headers()\n        self.wfile.write(b'unauthorized')\n"
        "HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()\n"
    )
    port = free_port()
    result = ValidateServiceTool(tmp_path).execute(
        [sys.executable, "server.py", "{port}"], port, "/login", "unauthorized",
        expected_status=401, method="POST", json_body={"password": "wrong"},
    )
    assert result.success and result.data["outcome"] == "passed"
    assert result.data["status"] == 401
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0


@pytest.mark.parametrize("cancel", [False, True])
def test_managed_timeout_and_cancel_cleanup(tmp_path, cancel):
    event = threading.Event()
    if cancel:
        event.set()
    service = ManagedProcess(tmp_path, [sys.executable, "-c", "import time; time.sleep(30)"], port=free_port(), timeout=.1, cancel=event)
    with pytest.raises(InterruptedError if cancel else TimeoutError):
        with service:
            service.wait_ready()
    assert service.process.poll() is not None


def test_batch_and_fact_layer_do_not_own_requirement_policy():
    root = Path(__file__).parents[1] / "agent"
    batch = (root / "orchestration/tool_batch_runner.py").read_text()
    assert "record_validation" not in batch and "RequirementEvidenceResolver" not in batch
    pipeline = (root / "validation/pipeline.py").read_text()
    assert "def next_action" not in pipeline and "CompletionPolicy" not in pipeline


def test_vibebench_executes_real_workspace_scenarios(tmp_path):
    from minicodex.evaluation.vibebench import run_vibebench
    summary = run_vibebench(tmp_path)
    assert summary.total_cases == 15
    assert all(r.error is None for r in summary.results)
    assert summary.vibe_metrics()["false_completion_rate"] == 0


def test_real_vibebench_is_provider_opt_in(tmp_path):
    from minicodex.evaluation.real_vibebench import run_real_vibebench
    with pytest.raises(ValueError, match="model_factory"):
        run_real_vibebench(tmp_path, model_factory=None)


def test_followup_reuses_session_without_task_evidence(tmp_path):
    from minicodex.agent.agent import MiniCodexAgent
    from minicodex.evaluation.vibebench import ScriptedModel, assertion, patch
    from minicodex.tools.editing import PatchFileTool
    from minicodex.tools.execution import RunCommandTool
    root = tmp_path / "examples"
    root.mkdir()
    (root / "a.py").write_text("VALUE = 1\n")
    registry = ToolRegistry()
    registry.register(PatchFileTool(tmp_path))
    registry.register(RunCommandTool(tmp_path))
    agent = MiniCodexAgent(llm=ScriptedModel((patch("examples/a.py", "VALUE = 1", "VALUE = 2"),
        assertion("examples/a.py", "VALUE = 2"), assertion("examples/a.py", "VALUE = 2"),
        assertion("examples/a.py", "VALUE = 2"))), registry=registry, planner=None, status_interval_seconds=0)
    agent.run("Set VALUE to 2 in examples/a.py.")
    session = agent.workspace_session
    first_run_id = agent.task_state.run_id
    agent.concrete_blockers.append("old task blocker")
    agent.run("Set VALUE to 2 in examples/a.py.")
    assert agent.workspace_session is session
    assert agent.task_state.run_id != first_run_id
    assert agent.validation_pipeline.state.edit_revision == 0
    assert len(agent.validation_pipeline.state.evidence_history) == 1
    assert agent.validation_pipeline.state.evidence_history[0].check_id == ""
    assert agent.validation_pipeline.state.proof("V1") is None
    assert not agent.concrete_blockers
    builds = session.build_count
    agent.run("Set VALUE to 2 in examples/a.py.")
    assert session.build_count == builds


def test_service_cleans_up_child_process_group(tmp_path):
    import os
    import subprocess
    import time
    command = "import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); Path('child.pid').write_text(str(p.pid)); time.sleep(30)"
    service = ManagedProcess(tmp_path, [sys.executable, "-c", command], port=free_port(), timeout=1)
    with pytest.raises(TimeoutError):
        with service:
            service.wait_ready()
    pid = int((tmp_path / "child.pid").read_text())
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    assert not state or state.startswith("Z")


def test_managed_process_refuses_unowned_port(tmp_path):
    with socket.socket() as other:
        other.bind(("127.0.0.1", 0))
        other.listen()
        service = ManagedProcess(tmp_path, [sys.executable, "-c", "pass"], port=other.getsockname()[1])
        with pytest.raises(OSError):
            service.start()
        assert service.process is None
        assert other.fileno() >= 0


def test_approval_hook_does_not_override_no_edit_constraint(tmp_path):
    from minicodex.agent.safety.safety import SafetyPolicy, InterventionCategory
    from minicodex.agent.safety.safety_executor import SafetyToolExecutor
    from minicodex.agent.runtime.tool_executor import ToolExecutor
    from minicodex.agent.runtime.tool_types import PreparedToolCall
    from minicodex.tools.editing import WriteFileTool
    registry = ToolRegistry()
    registry.register(WriteFileTool(tmp_path))
    policy = SafetyPolicy(workspace=tmp_path)
    policy.begin_task("Do not edit files", routed_intent="inspect_only")
    calls = []
    executor = SafetyToolExecutor(executor=ToolExecutor(registry), policy=policy, registry=registry,
                                  intervention_hook=lambda category, *args: calls.append(category))
    result = executor.execute_prepared(PreparedToolCall("write_file", {"path": "a.py", "content": "x=1"}))
    assert not result.result.success and calls == [InterventionCategory.CLARIFICATION]
    assert not (tmp_path / "a.py").exists()
