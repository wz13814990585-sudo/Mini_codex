"""Product-level tests for the dependency-free local Web UI."""

from __future__ import annotations

from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest

import minicodex.main as main_module
from ..agent.observability import TraceEventType, TraceRecorder
from ..agent.runtime import AsyncTaskStatus
from ..agent.runtime import PreparedToolCall
from ..agent.safety import PermissionMode, SafetyDecision, SafetyLevel
from ..llm import ModelConfig
from ..tools.results import ToolResult
from ..ui.server import (
    MiniCodexHTTPServer,
    MiniCodexUIController,
    UIRequestError,
    WorkspaceBrowser,
    create_ui_server,
)
from ..workspace import WorkspaceConfig


def _workspace_config(root: Path) -> WorkspaceConfig:
    runtime = root / ".runtime"
    return WorkspaceConfig(
        application_root=root,
        workspace_root=root,
        runtime_root=runtime,
        sandbox_root=runtime / "sandbox",
        trace_root=runtime / "traces",
        repository_key="ui-test",
    )


def _ready_model() -> ModelConfig:
    return ModelConfig("secret", "https://provider.example/v1", "test-model", "test")


class _FakeAgent:
    def __init__(self, recorder: TraceRecorder, *, with_edit: bool = True):
        self.trace_recorder = recorder
        self.llm = SimpleNamespace()
        self.tool_executor = SimpleNamespace()
        self.planner = None
        self.replanner = None
        self.undo_calls = 0
        checkpoint = SimpleNamespace(sealed=True, rolled_back=False)
        self.checkpoint_manager = SimpleNamespace(
            all_checkpoints=lambda: (checkpoint,) if with_edit else (),
        )
        self.task_state = SimpleNamespace(
            run_id="fake-run", mode=SimpleNamespace(value="standard"),
            intent=SimpleNamespace(value="modify"), phase=SimpleNamespace(value="done"),
            edit_revision=1 if with_edit else 0, validation_revision=1,
            remaining_steps=4, outcome=SimpleNamespace(value="edited_and_validated"),
            active_tool=None, acceptance_passed=True, relevant_validation_passed=True,
            full_validation_passed=False, latest_blocker=None,
            requirement_ids=("R1",), satisfied_requirement_ids=("R1",),
        )
        task_git = {
            "agent_current_changed_files": ["app.py"] if with_edit else [],
        }
        self.git_awareness = SimpleNamespace(
            task_state=lambda: SimpleNamespace(to_dict=lambda: task_git),
        )

    def run(self, user_input, use_planning=None, policy=None):
        self.trace_recorder.start_task(prompt=user_input)
        self.trace_recorder.emit(TraceEventType.LLM_STARTED, {})
        self.trace_recorder.emit(TraceEventType.LLM_FINISHED, {"total_tokens": 12})
        return f"Completed: {user_input}"

    def undo_task(self):
        self.undo_calls += 1
        return ToolResult(True, "Task changes were restored.", {"restored_paths": ["app.py"]})


class _ApprovalFakeAgent(_FakeAgent):
    def __init__(self, recorder: TraceRecorder):
        super().__init__(recorder, with_edit=False)
        self.safety_executor = SimpleNamespace(
            intervention_hook=None,
            permission_mode=PermissionMode.AUTO,
        )
        self.approved = None

    def run(self, user_input, use_planning=None, policy=None):
        self.trace_recorder.start_task(prompt=user_input)
        decision = SafetyDecision(
            SafetyLevel.CAUTION, True, "Dependency install needs approval.",
            "dependency_install", "install_python_package",
        )
        if self.safety_executor.permission_mode == PermissionMode.REVIEW:
            self.approved = self.safety_executor.intervention_hook(
                decision.intervention,
                decision,
                PreparedToolCall(
                    "install_python_package", {"package": "demo", "import_name": "demo"},
                ),
            )
        else:
            self.approved = True
        return "Approval flow finished."


def _controller(tmp_path: Path, *, with_edit: bool = True):
    observed = {}

    def factory(_config, *, model_config, output_level):
        recorder = TraceRecorder()
        agent = _FakeAgent(recorder, with_edit=with_edit)
        observed["agent"] = agent
        return agent, recorder, None

    controller = MiniCodexUIController(
        _workspace_config(tmp_path),
        _ready_model(),
        agent_factory=factory,
    )
    return controller, observed


def _wait_for_task(controller: MiniCodexUIController) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        task = controller.state()["task"]
        if task and task["done"]:
            return task
        time.sleep(0.01)
    pytest.fail("UI task did not finish")


def _wait_for_approval(controller: MiniCodexUIController) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        state = controller.state()
        pending = state["approval"]["pending"]
        if pending:
            return pending
        time.sleep(0.01)
    pytest.fail("UI approval did not become pending")


def test_workspace_browser_is_confined_and_skips_runtime_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=secret", encoding="utf-8")
    (tmp_path / ".env.example").write_text("API_KEY=", encoding="utf-8")
    (tmp_path / "benchmark_results").mkdir()
    (tmp_path / "benchmark_results" / "large.json").write_text("{}", encoding="utf-8")
    (tmp_path / "demo.egg-info").mkdir()
    (tmp_path / "demo.egg-info" / "PKG-INFO").write_text("metadata", encoding="utf-8")
    outside = tmp_path.parent / "outside-ui-test.txt"
    outside.write_text("outside", encoding="utf-8")

    browser = WorkspaceBrowser(tmp_path)
    tree = browser.tree()
    assert [node["name"] for node in tree["children"]] == ["src", ".env.example"]
    assert browser.read("src/app.py")["language"] == "python"
    with pytest.raises(UIRequestError, match="credential"):
        browser.read(".env")
    with pytest.raises(UIRequestError, match="工作区之外"):
        browser.read("../outside-ui-test.txt")


def test_controller_runs_agent_and_rejects_through_checkpoint_rollback(tmp_path):
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    controller, observed = _controller(tmp_path)

    started = controller.start_task("change app")
    assert started["status"] in {
        AsyncTaskStatus.PENDING.value,
        AsyncTaskStatus.RUNNING.value,
        AsyncTaskStatus.COMPLETED.value,
    }
    finished = _wait_for_task(controller)

    assert finished["review_status"] == "pending"
    assert controller.state()["messages"][-1]["content"] == "Completed: change app"
    rejected = controller.reject()
    assert rejected["review_status"] == "rejected"
    assert observed["agent"].undo_calls == 1


def test_controller_requires_review_before_next_task(tmp_path):
    controller, _observed = _controller(tmp_path)
    controller.start_task("first")
    _wait_for_task(controller)

    with pytest.raises(UIRequestError, match="Accept or reject"):
        controller.start_task("second")

    assert controller.accept()["review_status"] == "accepted"
    controller.start_task("second")
    assert _wait_for_task(controller)["done"] is True


def test_controller_can_open_without_a_model_but_cannot_start_task(tmp_path):
    model = ModelConfig(None, "https://api.deepseek.com", "deepseek-chat")
    controller = MiniCodexUIController(_workspace_config(tmp_path), model)

    assert controller.bootstrap()["model"]["configured"] is False
    with pytest.raises(UIRequestError) as error:
        controller.start_task("do work")
    assert error.value.status == 412
    with pytest.raises(ValueError, match="loopback"):
        create_ui_server(_workspace_config(tmp_path), model, host="0.0.0.0", port=0)


def test_controller_pauses_and_resumes_for_human_approval(tmp_path):
    observed = {}

    def factory(_config, *, model_config, output_level):
        recorder = TraceRecorder()
        agent = _ApprovalFakeAgent(recorder)
        observed["agent"] = agent
        return agent, recorder, None

    controller = MiniCodexUIController(
        _workspace_config(tmp_path), _ready_model(), agent_factory=factory,
    )
    controller.start_task("install dependency")
    pending = _wait_for_approval(controller)
    assert controller.state()["task"]["awaiting_approval"] is True

    response = controller.resolve_approval(pending["request_id"], "allow_once")
    assert response["resolved"]["decision"] == "allow_once"
    assert _wait_for_task(controller)["status"] == AsyncTaskStatus.COMPLETED.value
    assert observed["agent"].approved is True
    event_types = [event["event_type"] for event in controller.state()["events"]]
    assert "approval_requested" in event_types
    assert "approval_resolved" in event_types


def test_controller_auto_mode_skips_caution_prompt_and_records_mode(tmp_path):
    observed = {}

    def factory(_config, *, model_config, output_level):
        recorder = TraceRecorder()
        agent = _ApprovalFakeAgent(recorder)
        observed["agent"] = agent
        return agent, recorder, None

    controller = MiniCodexUIController(
        _workspace_config(tmp_path), _ready_model(), agent_factory=factory,
    )
    started = controller.start_task("install dependency", permission_mode="auto")

    assert started["permission_mode"] == "auto"
    assert _wait_for_task(controller)["status"] == AsyncTaskStatus.COMPLETED.value
    assert observed["agent"].approved is True
    assert controller.state()["approval"]["pending"] is None
    assert controller.state()["approval"]["audit"] == []


def test_controller_rejects_unknown_permission_mode(tmp_path):
    controller, _observed = _controller(tmp_path)

    with pytest.raises(UIRequestError, match="permission mode"):
        controller.start_task("inspect", permission_mode="unrestricted")


def test_controller_cancellation_rejects_pending_approval(tmp_path):
    observed = {}

    def factory(_config, *, model_config, output_level):
        recorder = TraceRecorder()
        agent = _ApprovalFakeAgent(recorder)
        observed["agent"] = agent
        return agent, recorder, None

    controller = MiniCodexUIController(
        _workspace_config(tmp_path), _ready_model(), agent_factory=factory,
    )
    controller.start_task("install dependency")
    _wait_for_approval(controller)
    controller.cancel_task()
    assert _wait_for_task(controller)["status"] == AsyncTaskStatus.CANCELLED.value
    assert observed["agent"].approved is False


def test_http_server_serves_shell_and_protects_mutations(tmp_path):
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    server = create_ui_server(_workspace_config(tmp_path), _ready_model(), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        html = response.read().decode("utf-8")
        assert response.status == 200
        assert "MiniCodex Workspace" in html
        assert 'data-mode="review"' in html
        assert 'id="diff-file-bar"' in html
        assert server.token in html
        assert "frame-ancestors 'none'" in response.getheader("Content-Security-Policy")

        connection.request(
            "POST", "/api/tasks", body='{"prompt":"test"}',
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 403
        response.read()

        connection.request("GET", "/", headers={"Host": "malicious.example"})
        response = connection.getresponse()
        assert response.status == 421
        response.read()
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_approval_endpoint_requires_token_and_matching_request(tmp_path):
    def factory(_config, *, model_config, output_level):
        recorder = TraceRecorder()
        return _ApprovalFakeAgent(recorder), recorder, None

    controller = MiniCodexUIController(
        _workspace_config(tmp_path), _ready_model(), agent_factory=factory,
    )
    server = MiniCodexHTTPServer(("127.0.0.1", 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    headers = {
        "Content-Type": "application/json",
        "X-MiniCodex-Token": server.token,
    }
    try:
        connection.request(
            "POST", "/api/tasks", body='{"prompt":"install dependency"}', headers=headers,
        )
        response = connection.getresponse()
        assert response.status == 202
        response.read()
        pending = _wait_for_approval(controller)

        connection.request(
            "POST", "/api/approvals",
            body='{"request_id":"stale","decision":"allow_once"}', headers=headers,
        )
        response = connection.getresponse()
        assert response.status == 409
        response.read()

        body = (
            '{"request_id":"' + pending["request_id"]
            + '","decision":"allow_once"}'
        )
        connection.request("POST", "/api/approvals", body=body, headers=headers)
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        assert _wait_for_task(controller)["status"] == AsyncTaskStatus.COMPLETED.value
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_ui_cli_dispatches_without_requiring_api_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in (
        "MINICODEX_API_KEY", "DEEPSEEK_API_KEY", "MINICODEX_BASE_URL",
        "DEEPSEEK_BASE_URL", "MINICODEX_MODEL", "DEEPSEEK_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    observed = {}

    def fake_run_ui(config, model_config, **kwargs):
        observed.update(
            workspace=config.workspace_root,
            configured=model_config.configured,
            **kwargs,
        )

    import minicodex.ui
    monkeypatch.setattr(minicodex.ui, "run_ui", fake_run_ui)
    assert main_module.main([
        "ui", "--workspace", str(tmp_path), "--port", "0", "--no-browser",
    ]) == 0
    assert observed["workspace"] == tmp_path.resolve()
    assert observed["configured"] is False
    assert observed["port"] == 0
    assert observed["open_browser"] is False
