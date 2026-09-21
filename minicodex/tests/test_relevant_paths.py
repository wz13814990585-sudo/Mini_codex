from types import SimpleNamespace

from ..agent.progress import ActionController
from ..agent.routing import ExecutionMode
from ..agent.routing import policy_for
from ..agent.validation import RelevantPathResolver
from ..agent.task_state import AgentPhase, TaskState


def test_relevant_paths_include_validation_failures_and_stale_targets(tmp_path):
    for relative in ("src/app.py", "tests/test_app.py", "src/helper.py"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    evidence = SimpleNamespace(
        path="tests/test_app.py",
        details={"failure_paths": ["tests/test_app.py", "src/helper.py", "../outside.py"]},
    )
    agent = SimpleNamespace(
        execution_route=SimpleNamespace(target_paths=("src/app.py",)),
        git_awareness=SimpleNamespace(
            task_state=lambda: SimpleNamespace(agent_touched_files=("src/app.py",))
        ),
        validation_pipeline=SimpleNamespace(state=SimpleNamespace(latest_evidence=evidence)),
        active_plan=None,
        edit_retry=SimpleNamespace(pending=SimpleNamespace(path="src/helper.py")),
    )

    relevant = RelevantPathResolver(tmp_path).resolve(agent)

    assert relevant.paths == ("src/app.py", "tests/test_app.py", "src/helper.py")
    assert "验证失败" in relevant.reasons["src/helper.py"]


def test_fixing_allows_targeted_read_of_traceback_path():
    state = TaskState(
        mode=ExecutionMode.STANDARD,
        phase=AgentPhase.FIXING,
        target_paths=("src/app.py",),
        relevant_paths=("src/app.py", "src/helper.py"),
    )
    controller = ActionController()
    controller.reset(state)
    controller.update_context(
        state=state,
        policy=policy_for(ExecutionMode.STANDARD),
        remaining_budget=5,
        acceptance_missing=True,
    )

    assert controller.restriction_reason(
        "read_file", {"path": "src/helper.py"}, policy_for(ExecutionMode.STANDARD)
    ) is None
    assert controller.restriction_reason(
        "read_file", {"path": "README.md"}, policy_for(ExecutionMode.STANDARD)
    ) is not None


def test_edit_paths_pinned_to_validation_targets():
    state = TaskState(
        mode=ExecutionMode.STANDARD,
        phase=AgentPhase.FIXING,
        target_paths=("app.py",),
        relevant_paths=("app.py",),
    )
    controller = ActionController()
    controller.reset(state)
    controller.update_context(
        state=state,
        policy=policy_for(ExecutionMode.STANDARD),
        remaining_budget=8,
        acceptance_missing=True,
        validation_paths=("app.py",),
    )
    policy = policy_for(ExecutionMode.STANDARD)
    assert controller.restriction_reason("write_file", {"path": "app.py"}, policy) is None
    reason = controller.restriction_reason("write_file", {"path": "login.py"}, policy)
    assert reason is not None
    assert "app.py" in reason
    assert "login.py" in reason
    force = controller.force_edit_instruction()
    assert "app.py" in force
    assert "write_file" in force


def test_python_behavior_blocks_validate_service_drift():
    state = TaskState(
        mode=ExecutionMode.STANDARD,
        phase=AgentPhase.FIXING,
        target_paths=("app.py",),
        relevant_paths=("app.py",),
    )
    controller = ActionController()
    controller.reset(state)
    controller.update_context(
        state=state,
        policy=policy_for(ExecutionMode.STANDARD),
        remaining_budget=8,
        acceptance_missing=True,
        next_required_check_id="V1",
        next_contract_type="python_behavior",
        validation_paths=("app.py",),
    )
    reason = controller.restriction_reason(
        "validate_service",
        {"path": "/login", "method": "POST"},
        policy_for(ExecutionMode.STANDARD),
    )
    assert reason is not None
    assert "python_behavior" in reason
    assert "validate_service" in reason


def test_blocks_typed_typescript_and_fastapi_framework_rewrite():
    state = TaskState(
        mode=ExecutionMode.STANDARD,
        phase=AgentPhase.ACTING,
        target_paths=("src/range.ts", "app.py"),
        relevant_paths=("src/range.ts", "app.py"),
    )
    controller = ActionController()
    controller.reset(state)
    controller.update_context(
        state=state,
        policy=policy_for(ExecutionMode.STANDARD),
        remaining_budget=8,
        next_contract_type="node_behavior",
        validation_paths=("src/range.ts", "app.py"),
        baseline_web_framework="fastapi",
    )
    policy = policy_for(ExecutionMode.STANDARD)
    typed = controller.restriction_reason(
        "write_file",
        {
            "path": "src/range.ts",
            "content": "export function inclusiveRange(start: number, end: number): number[] { return [] }",
        },
        policy,
    )
    assert typed is not None and "类型注解" in typed
    plain = controller.restriction_reason(
        "write_file",
        {
            "path": "src/range.ts",
            "content": "export function inclusiveRange(start, end) {\n  const out = []\n  return out\n}\n",
        },
        policy,
    )
    assert plain is None
    flask_rewrite = controller.restriction_reason(
        "write_file",
        {
            "path": "app.py",
            "content": "from flask import Flask\napp=Flask(__name__)\n",
        },
        policy,
    )
    assert flask_rewrite is not None and "FastAPI" in flask_rewrite


def test_force_edit_lists_move_symbol_paths():
    state = TaskState(
        mode=ExecutionMode.STANDARD,
        phase=AgentPhase.ACTING,
        target_paths=("src/service.py", "src/parser.py"),
        relevant_paths=("src/service.py", "src/parser.py"),
    )
    controller = ActionController()
    controller.reset(state)
    controller.update_context(
        state=state,
        policy=policy_for(ExecutionMode.STANDARD),
        remaining_budget=10,
        next_required_check_id="V1",
        validation_paths=("src/service.py", "src/parser.py"),
    )
    force = controller.force_edit_instruction()
    assert "src/parser.py" in force and "src/service.py" in force
    assert controller.restriction_reason(
        "write_file", {"path": "src/parser.py"}, policy_for(ExecutionMode.STANDARD)
    ) is None
    assert controller.restriction_reason(
        "write_file", {"path": "other.py"}, policy_for(ExecutionMode.STANDARD)
    ) is not None


def test_relevant_paths_add_manifest_only_for_dependency_evidence(tmp_path):
    for relative in ("src/app.py", "pyproject.toml"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    agent = SimpleNamespace(
        execution_route=SimpleNamespace(target_paths=("src/app.py",)),
        git_awareness=None,
        validation_pipeline=SimpleNamespace(
            state=SimpleNamespace(
                latest_evidence=SimpleNamespace(
                    path="tests/test_app.py",
                    details={"failure_type": "missing_dependency"},
                )
            )
        ),
        active_plan=None,
        edit_retry=None,
        latest_dependency_resolution=None,
        latest_symbol_recovery_paths=(),
    )

    relevant = RelevantPathResolver(tmp_path).resolve(agent)

    assert "pyproject.toml" in relevant.paths


def test_relevant_paths_include_symbol_search_recovery_matches(tmp_path):
    target = tmp_path / "src/worker.py"
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")
    agent = SimpleNamespace(
        execution_route=SimpleNamespace(target_paths=()),
        git_awareness=None,
        validation_pipeline=SimpleNamespace(state=SimpleNamespace(latest_evidence=None)),
        active_plan=None,
        edit_retry=None,
        latest_dependency_resolution=None,
        latest_symbol_recovery_paths=("src/worker.py",),
    )

    relevant = RelevantPathResolver(tmp_path).resolve(agent)

    assert relevant.reasons["src/worker.py"] == ("符号搜索恢复",)
