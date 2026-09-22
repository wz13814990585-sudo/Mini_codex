"""A dependency-free local Web shell around the existing MiniCodex runtime."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import mimetypes
from pathlib import Path
import secrets
import socket
import threading
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
import webbrowser

from .. import __version__
from ..agent.runtime import AsyncAgentRunner, GitRepositoryInspector
from ..agent.safety import ApprovalCoordinator, PermissionMode
from ..doctor import diagnose
from ..llm import ModelConfig, ModelConfigurationError
from ..utils.paths import resolve_workspace_path
from ..workspace import WorkspaceConfig


_IGNORED_DIRECTORIES = frozenset({
    ".git", ".minicodex", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", ".venv", "__pycache__", "benchmark_results", "build", "dist",
    "node_modules",
})
_SENSITIVE_FILE_NAMES = frozenset({
    ".env", ".git-credentials", ".netrc", ".npmrc", ".pypirc",
    "id_dsa", "id_ed25519", "id_ecdsa", "id_rsa",
})
_SENSITIVE_FILE_SUFFIXES = frozenset({".key", ".p12", ".pfx", ".pem"})
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_FILE_BYTES = 2 * 1024 * 1024


class UIRequestError(ValueError):
    """Expected API error with an HTTP status."""

    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = int(status)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


class WorkspaceBrowser:
    """Read-only, workspace-confined file browsing for the UI."""

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()

    def tree(self, *, max_files: int = 2500, max_depth: int = 8) -> dict[str, Any]:
        remaining = [max(1, int(max_files))]
        truncated = [False]

        def visit(directory: Path, depth: int) -> list[dict[str, Any]]:
            if depth > max_depth:
                truncated[0] = True
                return []
            try:
                entries = sorted(
                    directory.iterdir(),
                    key=lambda item: (not item.is_dir(), item.name.casefold()),
                )
            except OSError:
                return []
            nodes: list[dict[str, Any]] = []
            for entry in entries:
                if remaining[0] <= 0:
                    truncated[0] = True
                    break
                if (
                    entry.is_symlink()
                    or (
                        entry.is_dir()
                        and (
                            entry.name in _IGNORED_DIRECTORIES
                            or entry.name.endswith(".egg-info")
                        )
                    )
                    or (entry.is_file() and _is_sensitive_file(entry))
                ):
                    continue
                try:
                    relative = entry.relative_to(self.workspace).as_posix()
                    is_directory = entry.is_dir()
                except (OSError, ValueError):
                    continue
                remaining[0] -= 1
                node: dict[str, Any] = {
                    "name": entry.name,
                    "path": relative,
                    "type": "directory" if is_directory else "file",
                }
                if is_directory:
                    node["children"] = visit(entry, depth + 1)
                nodes.append(node)
            return nodes

        return {
            "name": self.workspace.name,
            "path": "",
            "type": "directory",
            "children": visit(self.workspace, 0),
            "truncated": truncated[0],
        }

    def read(self, relative_path: str) -> dict[str, Any]:
        normalized = str(relative_path or "").strip()
        if not normalized:
            raise UIRequestError("File path is required.")
        try:
            target = resolve_workspace_path(self.workspace, normalized)
        except ValueError as exc:
            raise UIRequestError(str(exc), HTTPStatus.FORBIDDEN) from exc
        if not target.is_file():
            raise UIRequestError("File does not exist.", HTTPStatus.NOT_FOUND)
        if _is_sensitive_file(target):
            raise UIRequestError("Sensitive credential files cannot be previewed.", HTTPStatus.FORBIDDEN)
        if target.stat().st_size > _MAX_FILE_BYTES:
            raise UIRequestError("File is too large to preview.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        content = target.read_bytes()
        if b"\x00" in content[:8192]:
            raise UIRequestError("Binary files cannot be previewed.", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        return {
            "path": target.relative_to(self.workspace).as_posix(),
            "content": content.decode("utf-8", errors="replace"),
            "size": len(content),
            "language": _language_for(target.suffix),
        }


def _language_for(suffix: str) -> str:
    return {
        ".css": "css", ".html": "html", ".js": "javascript", ".json": "json",
        ".md": "markdown", ".py": "python", ".toml": "toml", ".ts": "typescript",
        ".tsx": "tsx", ".yml": "yaml", ".yaml": "yaml",
    }.get(suffix.casefold(), "text")


def _is_sensitive_file(path: Path) -> bool:
    name = path.name.casefold()
    if name in _SENSITIVE_FILE_NAMES or path.suffix.casefold() in _SENSITIVE_FILE_SUFFIXES:
        return True
    return name.startswith(".env.") and name != ".env.example"


class MiniCodexUIController:
    """Own one local UI session while delegating all coding work to the Harness."""

    def __init__(
        self,
        config: WorkspaceConfig,
        model_config: ModelConfig,
        *,
        output_level: str = "normal",
        agent_factory: Callable[..., tuple[Any, Any, Any]] | None = None,
        runner_factory: Callable[..., Any] = AsyncAgentRunner,
    ) -> None:
        self.config = config
        self.model_config = model_config
        self.output_level = output_level
        self.browser = WorkspaceBrowser(config.workspace_root)
        self.git = GitRepositoryInspector(config.workspace_root)
        self._agent_factory = agent_factory or self._default_agent_factory
        self._runner_factory = runner_factory
        self._lock = threading.RLock()
        self._agent = None
        self._recorder = None
        self._task = None
        self._result = None
        self._review_status = "not_required"
        self._messages: list[dict[str, Any]] = []
        self._approval = ApprovalCoordinator()
        self._permission_mode = PermissionMode.REVIEW

    @staticmethod
    def _default_agent_factory(config, *, model_config, output_level):
        from ..main import build_agent

        return build_agent(config, model_config=model_config, output_level=output_level)

    def bootstrap(self) -> dict[str, Any]:
        report = diagnose(self.config, self.model_config, connect=False)
        return {
            "version": __version__,
            "workspace": {
                "name": self.config.workspace_root.name,
                "path": str(self.config.workspace_root),
            },
            "model": {
                "configured": self.model_config.configured,
                "model": self.model_config.model,
                "base_url": self.model_config.base_url,
                "api_key_source": self.model_config.api_key_source,
                "problems": list(self.model_config.problems()),
            },
            "doctor": report.to_dict(),
            "state": self.state(),
        }

    def start_task(
        self,
        prompt: str,
        permission_mode: str | PermissionMode | None = None,
    ) -> dict[str, Any]:
        prompt = str(prompt or "").strip()
        if not prompt:
            raise UIRequestError("Task prompt cannot be empty.")
        if len(prompt) > 20_000:
            raise UIRequestError("Task prompt is too long.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            self.model_config.require_ready()
        except ModelConfigurationError as exc:
            raise UIRequestError(str(exc), HTTPStatus.PRECONDITION_FAILED) from exc
        try:
            selected_mode = PermissionMode(permission_mode or self._permission_mode)
        except ValueError as exc:
            raise UIRequestError("Unknown permission mode.") from exc

        with self._lock:
            if self._task is not None and not self._task.done:
                raise UIRequestError("A task is already running.", HTTPStatus.CONFLICT)
            if self._review_status == "pending":
                raise UIRequestError(
                    "Accept or reject the current changes before starting another task.",
                    HTTPStatus.CONFLICT,
                )
            self._approval.begin_task()
            agent, recorder, _memory = self._agent_factory(
                self.config,
                model_config=self.model_config,
                output_level=self.output_level,
            )
            self._permission_mode = selected_mode
            self._install_permission_mode(agent, recorder, selected_mode)
            runner = self._runner_factory(agent=agent)
            task = runner.start(prompt)
            self._agent = agent
            self._recorder = recorder
            self._task = task
            self._result = None
            self._review_status = "running"
            self._messages.append({
                "id": f"user-{task.task_id}",
                "role": "user",
                "content": prompt,
                "created_at": _utc_now(),
            })
            threading.Thread(
                target=self._watch_task,
                args=(task, recorder),
                name=f"MiniCodex-UI-watch-{task.task_id[:8]}",
                daemon=True,
            ).start()
            return self._task_payload()

    def _watch_task(self, task, recorder) -> None:
        result = task.wait()
        if result is None:
            return
        try:
            self.config.trace_root.mkdir(parents=True, exist_ok=True)
            recorder.save_jsonl(self.config.trace_root / "latest.jsonl")
            recorder.save_jsonl(self.config.trace_root / f"{task.task_id}.jsonl")
        except OSError:
            pass
        self._finalize_task(task, result)

    def _finalize_task(self, task, result) -> None:
        """Publish one terminal result exactly once, even across poll/watcher races."""

        with self._lock:
            if self._task is not task or self._result is not None:
                return
            self._result = result
            has_edits = self._has_rejectable_edits()
            self._review_status = "pending" if has_edits else "not_required"
            content = result.output or result.error or "Task finished without output."
            self._messages.append({
                "id": f"assistant-{task.task_id}",
                "role": "assistant",
                "content": content,
                "status": result.status.value,
                "created_at": _utc_now(),
            })

    def cancel_task(self) -> dict[str, Any]:
        with self._lock:
            if self._task is None or self._task.done:
                raise UIRequestError("No running task to cancel.", HTTPStatus.CONFLICT)
            self._approval.cancel_pending("Cancelled from the MiniCodex UI.")
            self._task.cancel("Cancelled from the MiniCodex UI.")
            return self._task_payload()

    def resolve_approval(self, request_id: str, decision: str) -> dict[str, Any]:
        try:
            resolved = self._approval.resolve(request_id, decision)
        except ValueError as exc:
            raise UIRequestError(str(exc), HTTPStatus.CONFLICT) from exc
        return {
            "resolved": resolved,
            "approval": self._approval.snapshot(),
            "task": self._task_payload(),
        }

    def _install_permission_mode(
        self,
        agent: Any,
        recorder: Any,
        mode: PermissionMode,
    ) -> None:
        self._approval.set_event_sink(getattr(recorder, "emit", None))
        executor = getattr(agent, "safety_executor", None)
        if executor is None:
            executor = getattr(agent, "tool_executor", None)
            seen: set[int] = set()
            while executor is not None and id(executor) not in seen:
                seen.add(id(executor))
                if hasattr(executor, "intervention_hook"):
                    break
                executor = getattr(executor, "executor", None)
        if executor is None:
            return
        if hasattr(executor, "set_permission_mode"):
            executor.set_permission_mode(mode)
        else:
            executor.permission_mode = mode
        if hasattr(executor, "intervention_hook"):
            executor.intervention_hook = (
                self._approval.intervene if mode == PermissionMode.REVIEW else None
            )

    def accept(self) -> dict[str, Any]:
        with self._lock:
            self._require_pending_review()
            self._review_status = "accepted"
            return self._task_payload()

    def reject(self) -> dict[str, Any]:
        with self._lock:
            self._require_pending_review()
            result = self._agent.undo_task()
            if not result.success:
                raise UIRequestError(
                    result.error or result.summary or "Unable to reject task changes.",
                    HTTPStatus.CONFLICT,
                )
            self._review_status = "rejected"
            self._messages.append({
                "id": f"system-reject-{self._task.task_id}",
                "role": "system",
                "content": result.summary,
                "created_at": _utc_now(),
            })
            return self._task_payload()

    def _require_pending_review(self) -> None:
        if self._task is None or not self._task.done or self._review_status != "pending":
            raise UIRequestError("No completed change set is awaiting review.", HTTPStatus.CONFLICT)

    def _has_rejectable_edits(self) -> bool:
        manager = getattr(self._agent, "checkpoint_manager", None)
        if manager is None:
            return False
        return any(
            checkpoint.sealed and not checkpoint.rolled_back
            for checkpoint in manager.all_checkpoints()
        )

    def state(self, *, after_sequence: int = 0) -> dict[str, Any]:
        task_snapshot = self._task
        if task_snapshot is not None and task_snapshot.done and self._result is None:
            result = task_snapshot.result_now
            if result is not None:
                self._finalize_task(task_snapshot, result)
        with self._lock:
            task = self._task_payload()
            recorder = self._recorder
            messages = list(self._messages)
            agent = self._agent
        events = []
        summary = None
        if recorder is not None:
            try:
                events = [
                    event.to_dict() for event in list(recorder.events)
                    if event.sequence > max(0, int(after_sequence))
                ]
                summary = recorder.summary().to_dict()
            except (AttributeError, RuntimeError):
                events = []
        runtime = _runtime_payload(getattr(agent, "task_state", None))
        git_state = self.git.snapshot().to_dict()
        task_git = None
        if agent is not None:
            try:
                task_git = agent.git_awareness.task_state().to_dict()
            except Exception:
                task_git = None
        return {
            "task": task,
            "runtime": runtime,
            "trace_summary": summary,
            "events": events,
            "messages": messages,
            "git": git_state,
            "task_git": task_git,
            "approval": self._approval.snapshot(),
            "permission_mode": self._permission_mode.value,
            "permission_modes": [mode.value for mode in PermissionMode],
        }

    def _task_payload(self) -> dict[str, Any] | None:
        if self._task is None:
            return None
        result = self._result or self._task.result_now
        return {
            "id": self._task.task_id,
            "status": self._task.status.value,
            "done": self._task.done,
            "review_status": self._review_status,
            "output": result.output if result else None,
            "error": result.error if result else None,
            "duration_seconds": result.duration_seconds if result else None,
            "can_cancel": not self._task.done,
            "can_review": self._task.done and self._review_status == "pending",
            "awaiting_approval": self._approval.snapshot()["pending"] is not None,
            "permission_mode": self._permission_mode.value,
        }

    def diff(self, path: str | None = None) -> dict[str, Any]:
        normalized = str(path or "").strip() or None
        result = self.git.diff(path=normalized, staged=False, max_chars=500_000)
        if not result.success:
            raise UIRequestError(result.error or "Unable to read Git diff.", HTTPStatus.CONFLICT)
        return asdict(result)


def _runtime_payload(state: Any) -> dict[str, Any] | None:
    if state is None:
        return None
    return {
        "run_id": state.run_id,
        "mode": _enum_value(state.mode),
        "intent": _enum_value(state.intent),
        "phase": _enum_value(state.phase),
        "edit_revision": state.edit_revision,
        "validation_revision": state.validation_revision,
        "remaining_steps": state.remaining_steps,
        "outcome": _enum_value(state.outcome),
        "active_tool": state.active_tool,
        "acceptance_passed": state.acceptance_passed,
        "relevant_validation_passed": state.relevant_validation_passed,
        "full_validation_passed": state.full_validation_passed,
        "latest_blocker": state.latest_blocker,
        "requirement_count": len(state.requirement_ids),
        "satisfied_requirement_count": len(state.satisfied_requirement_ids),
    }


class MiniCodexHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, controller: MiniCodexUIController):
        self.controller = controller
        self.token = secrets.token_urlsafe(32)
        self.static_root = Path(__file__).resolve().parent / "static"
        if ":" in str(server_address[0]):
            self.address_family = socket.AF_INET6
        super().__init__(server_address, MiniCodexRequestHandler)


class MiniCodexRequestHandler(BaseHTTPRequestHandler):
    """Small same-origin JSON API and static-file server."""

    server: MiniCodexHTTPServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._valid_host():
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "Invalid local UI host.")
            return
        route = urlparse(self.path)
        try:
            if route.path == "/api/bootstrap":
                self._json(self.server.controller.bootstrap())
            elif route.path == "/api/state":
                query = parse_qs(route.query)
                after = int(query.get("after", ["0"])[0])
                self._json(self.server.controller.state(after_sequence=after))
            elif route.path == "/api/tree":
                self._json(self.server.controller.browser.tree())
            elif route.path == "/api/file":
                query = parse_qs(route.query)
                self._json(self.server.controller.browser.read(query.get("path", [""])[0]))
            elif route.path == "/api/diff":
                query = parse_qs(route.query)
                self._json(self.server.controller.diff(query.get("path", [""])[0]))
            elif route.path in {"/", "/index.html"}:
                index = (self.server.static_root / "index.html").read_text(encoding="utf-8")
                index = index.replace("__MINICODEX_TOKEN__", self.server.token)
                self._bytes(index.encode("utf-8"), "text/html; charset=utf-8")
            elif route.path.startswith("/static/"):
                self._static(route.path.removeprefix("/static/"))
            else:
                self._error(HTTPStatus.NOT_FOUND, "Not found.")
        except UIRequestError as exc:
            self._error(exc.status, str(exc))
        except (OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unexpected local UI error.")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._valid_host():
            self.close_connection = True
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "Invalid local UI host.")
            return
        try:
            payload = self._request_json()
        except UIRequestError as exc:
            self._error(exc.status, str(exc))
            return
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if not hmac.compare_digest(
            self.headers.get("X-MiniCodex-Token", ""), self.server.token,
        ):
            self._error(HTTPStatus.FORBIDDEN, "Invalid UI session token.")
            return
        try:
            route = urlparse(self.path).path
            if route == "/api/tasks":
                result = self.server.controller.start_task(
                    payload.get("prompt", ""), payload.get("permission_mode"),
                )
                self._json(result, HTTPStatus.ACCEPTED)
            elif route == "/api/tasks/cancel":
                self._json(self.server.controller.cancel_task())
            elif route == "/api/tasks/accept":
                self._json(self.server.controller.accept())
            elif route == "/api/tasks/reject":
                self._json(self.server.controller.reject())
            elif route == "/api/approvals":
                self._json(self.server.controller.resolve_approval(
                    payload.get("request_id", ""), payload.get("decision", ""),
                ))
            else:
                self._error(HTTPStatus.NOT_FOUND, "Not found.")
        except UIRequestError as exc:
            self._error(exc.status, str(exc))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unexpected local UI error.")

    def _request_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise UIRequestError("Invalid Content-Length.") from exc
        if length < 0 or length > _MAX_REQUEST_BYTES:
            self.close_connection = True
            raise UIRequestError("Request body is too large.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        raw = self.rfile.read(length)
        if not raw:
            return {}
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise UIRequestError("JSON body must be an object.")
        return value

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "").strip().casefold()
        if host.startswith("["):
            hostname = host.split("]", 1)[0].removeprefix("[")
        else:
            hostname = host.split(":", 1)[0]
        return hostname in {"127.0.0.1", "localhost", "::1"}

    def _static(self, name: str) -> None:
        if name not in {"app.js", "styles.css"}:
            self._error(HTTPStatus.NOT_FOUND, "Not found.")
            return
        target = self.server.static_root / name
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._bytes(target.read_bytes(), f"{content_type}; charset=utf-8")

    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        self._bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _bytes(self, body: bytes, content_type: str, status: int = HTTPStatus.OK) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def create_ui_server(
    config: WorkspaceConfig,
    model_config: ModelConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    output_level: str = "normal",
) -> MiniCodexHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("MiniCodex UI only binds to a loopback address.")
    if not 0 <= int(port) <= 65535:
        raise ValueError("UI port must be between 0 and 65535.")
    controller = MiniCodexUIController(config, model_config, output_level=output_level)
    return MiniCodexHTTPServer((host, int(port)), controller)


def run_ui(
    config: WorkspaceConfig,
    model_config: ModelConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    output_level: str = "normal",
    open_browser: bool = True,
) -> None:
    server = create_ui_server(
        config,
        model_config,
        host=host,
        port=port,
        output_level=output_level,
    )
    actual_host, actual_port = server.server_address[:2]
    display_host = "127.0.0.1" if actual_host in {"0.0.0.0", "::"} else actual_host
    rendered_host = f"[{display_host}]" if ":" in display_host else display_host
    url = f"http://{rendered_host}:{actual_port}/"
    print(f"MiniCodex UI: {url}")
    print(f"Workspace: {config.workspace_root}")
    if open_browser:
        threading.Timer(0.15, partial(webbrowser.open, url)).start()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
