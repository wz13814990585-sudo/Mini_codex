from types import SimpleNamespace

from ..agent.action_controller import ActionController
from ..agent.execution_mode import ExecutionMode
from ..agent.execution_policy import policy_for
from ..agent.relevant_paths import RelevantPathResolver
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
    assert "validation failure" in relevant.reasons["src/helper.py"]


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
