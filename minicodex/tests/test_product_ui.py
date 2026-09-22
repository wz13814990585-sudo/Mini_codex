"""Product-level tests for the local Web UI and bundled frontend."""

from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest

import minicodex.main as main_module
from ..agent.observability import TraceEventType, TraceRecorder
from ..agent.editing.checkpoint import CheckpointManager
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
from ..ui.terminal import TerminalError, WorkspaceTerminal
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
    with pytest.raises(UIRequestError, match="not available"):
        browser.read(".git/config")
    with pytest.raises(UIRequestError, match="credential"):
        browser.read(".env")
    with pytest.raises(UIRequestError, match="工作区之外"):
        browser.read("../outside-ui-test.txt")


def test_workspace_browser_manual_save_is_confined_and_revision_checked(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=yes", encoding="utf-8")
    browser = WorkspaceBrowser(tmp_path)
    first = browser.read("app.py")
    assert first["editable"] is True
    saved = browser.save("app.py", "value = 2\n", first["revision"])
    assert saved["revision"] != first["revision"]
    assert source.read_text(encoding="utf-8") == "value = 2\n"
    with pytest.raises(UIRequestError, match="changed on disk") as stale:
        browser.save("app.py", "value = 3\n", first["revision"])
    assert stale.value.status == 409
    with pytest.raises(UIRequestError, match="credential"):
        browser.save(".env", "SECRET=no", first["revision"])
    with pytest.raises(UIRequestError, match="工作区之外"):
        browser.save("../outside.py", "x", first["revision"])
    assert source.read_text(encoding="utf-8") == "value = 2\n"


def test_workspace_browser_create_rename_and_recoverable_trash(tmp_path):
    browser = WorkspaceBrowser(tmp_path)
    folder = browser.create("src", kind="directory")
    assert folder["type"] == "directory"
    created = browser.create("src/app.py")
    assert created["content"] == ""
    (tmp_path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    fresh = browser.read("src/app.py")
    with pytest.raises(UIRequestError, match="changed on disk"):
        browser.rename("src/app.py", "src/new.py", expected_revision=created["revision"])
    renamed = browser.rename("src/app.py", "src/new.py", expected_revision=fresh["revision"])
    assert renamed["path"] == "src/new.py"
    with pytest.raises(UIRequestError, match="relative path"):
        browser.create("../outside.py")
    with pytest.raises(UIRequestError, match="cannot be changed"):
        browser.create(".env")
    with pytest.raises(UIRequestError, match="not available"):
        browser.create(".git/config")
    with pytest.raises(UIRequestError, match="already exists"):
        browser.create("src/new.py")
    removed = browser.trash("src/new.py", expected_revision=fresh["revision"])
    assert not (tmp_path / "src" / "new.py").exists()
    assert (tmp_path / removed["trash_path"]).read_text(encoding="utf-8") == "print('ok')\n"


def test_workspace_terminal_is_real_pty_and_bounded(tmp_path):
    terminal = WorkspaceTerminal(tmp_path, shell="/bin/sh")
    with pytest.raises(TerminalError, match="size"):
        terminal.start(cols=1, rows=1)
    started = terminal.start(cols=80, rows=24)
    assert started["running"] is True
    try:
        terminal.write("pwd; printf 'PTY_READY\\n'; exit\n")
        deadline = time.monotonic() + 5
        output = ""
        while time.monotonic() < deadline:
            snapshot = terminal.snapshot()
            output = "".join(chunk["data"] for chunk in snapshot["chunks"])
            if "PTY_READY" in output and not snapshot["running"]:
                break
            time.sleep(0.02)
        assert str(tmp_path) in output
        assert "PTY_READY" in output
        assert terminal.snapshot(after=terminal.snapshot()["sequence"])["chunks"] == []
    finally:
        terminal.stop()
    assert terminal.running is False


def test_controller_manual_save_waits_for_agent_review(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    controller, _ = _controller(tmp_path)
    revision = controller.browser.read("app.py")["revision"]
    controller.start_task("change app")
    _wait_for_task(controller)
    with pytest.raises(UIRequestError, match="Accept or reject"):
        controller.save_file("app.py", "value = 2\n", revision)
    controller.accept()
    saved = controller.save_file("app.py", "value = 2\n", revision)
    assert saved["content"] == "value = 2\n"


def test_controller_keeps_shell_and_agent_tasks_separate(tmp_path):
    controller, _ = _controller(tmp_path)
    controller.terminal.shell = "/bin/sh"
    controller.start_terminal(cols=80, rows=24)
    try:
        with pytest.raises(UIRequestError, match="Close the interactive terminal"):
            controller.start_task("change app")
    finally:
        controller.stop_terminal()
    controller.start_task("change app")
    assert _wait_for_task(controller)["review_status"] == "pending"
    with pytest.raises(UIRequestError, match="Accept or reject"):
        controller.start_terminal(cols=80, rows=24)


def test_non_git_workspace_uses_agent_checkpoints_for_review_diff(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    manager = CheckpointManager(tmp_path)
    checkpoint = manager.capture(path="app.py", edit_revision=1)
    source.write_text("value = 2\n", encoding="utf-8")
    manager.seal(checkpoint.checkpoint_id)
    controller = MiniCodexUIController(_workspace_config(tmp_path), _ready_model())
    controller._agent = SimpleNamespace(checkpoint_manager=manager)

    assert controller.state()["task_git"]["agent_current_changed_files"] == ["app.py"]
    diff = controller.diff("app.py")
    assert diff["success"] is True
    assert "-value = 1" in diff["text"]
    assert "+value = 2" in diff["text"]
    with pytest.raises(UIRequestError, match="工作区之外"):
        controller.diff("../outside.py")

    source.write_text("value = 3\n", encoding="utf-8")
    with pytest.raises(UIRequestError, match="changed after") as stale:
        controller.diff("app.py")
    assert stale.value.status == 409


def test_non_git_new_file_has_reviewable_diff(tmp_path):
    manager = CheckpointManager(tmp_path)
    checkpoint = manager.capture(path="index.html", edit_revision=1)
    (tmp_path / "index.html").write_text("<h1>Snake</h1>\n", encoding="utf-8")
    manager.seal(checkpoint.checkpoint_id)
    controller = MiniCodexUIController(_workspace_config(tmp_path), _ready_model())
    controller._agent = SimpleNamespace(checkpoint_manager=manager)

    diff = controller.diff("index.html")
    assert "--- /dev/null" in diff["text"]
    assert "+++ b/index.html" in diff["text"]
    assert "+<h1>Snake</h1>" in diff["text"]


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
    server.controller.terminal.shell = "/bin/sh"
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
        policy = response.getheader("Content-Security-Policy")
        assert "frame-ancestors 'none'" in policy
        assert f"style-src 'self' 'nonce-{server.token}'" in policy
        assert "script-src 'self'" in policy
        assert "'unsafe-inline'" not in policy
        for asset in ("app.bundle.js", "app.bundle.css"):
            connection.request("GET", f"/static/{asset}")
            response = connection.getresponse()
            assert response.status == 200
            assert len(response.read()) > 1000

        connection.request(
            "POST", "/api/tasks", body='{"prompt":"test"}',
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 403
        response.read()

        connection.request("GET", "/api/file?path=README.md")
        response = connection.getresponse()
        file_state = json.loads(response.read())
        assert response.status == 200
        save_body = json.dumps({
            "path": "README.md", "content": "# Updated\n",
            "expected_revision": file_state["revision"],
        })
        connection.request(
            "POST", "/api/file", body=save_body,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 403
        response.read()
        connection.request(
            "POST", "/api/file", body=save_body,
            headers={
                "Content-Type": "application/json",
                "X-MiniCodex-Token": server.token,
            },
        )
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["content"] == "# Updated\n"
        assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# Updated\n"

        mutation_headers = {"Content-Type": "application/json", "X-MiniCodex-Token": server.token}
        connection.request(
            "POST", "/api/items/create", body='{"path":"scratch.py","kind":"file"}',
            headers=mutation_headers,
        )
        response = connection.getresponse()
        assert response.status == 201
        new_file = json.loads(response.read())
        assert new_file["path"] == "scratch.py"
        connection.request(
            "POST", "/api/items/rename",
            body=json.dumps({"path": "scratch.py", "new_path": "renamed.py",
                             "expected_revision": new_file["revision"]}),
            headers=mutation_headers,
        )
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        connection.request(
            "POST", "/api/items/trash",
            body=json.dumps({"path": "renamed.py", "expected_revision": new_file["revision"]}),
            headers=mutation_headers,
        )
        response = connection.getresponse()
        assert response.status == 200
        trashed = json.loads(response.read())
        assert (tmp_path / trashed["trash_path"]).is_file()

        connection.request("GET", "/api/terminal?after=0")
        response = connection.getresponse()
        assert response.status == 403
        response.read()
        terminal_headers = mutation_headers
        connection.request(
            "POST", "/api/terminal/start", body='{"cols":80,"rows":24}', headers=terminal_headers,
        )
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["running"] is True
        connection.request(
            "POST", "/api/terminal/input", body=json.dumps({"data": "printf 'HTTP_PTY_OK\\n'; exit\n"}),
            headers=terminal_headers,
        )
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        observed = ""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and "HTTP_PTY_OK" not in observed:
            connection.request("GET", "/api/terminal?after=0", headers=terminal_headers)
            response = connection.getresponse()
            assert response.status == 200
            observed = "".join(chunk["data"] for chunk in json.loads(response.read())["chunks"])
            time.sleep(0.02)
        assert "HTTP_PTY_OK" in observed

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
