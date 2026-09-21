"""Bounded local service lifecycle using the existing process sandbox settings."""
from collections import deque
import os
import signal
import socket
import subprocess
import threading
import time

from ..safety.sandbox import SandboxRunner, SandboxLimits
from .execution_control import ACTIVE_CANCELLATION


class ManagedProcess:
    def __init__(self, workspace, argv, *, port, timeout=15, cancel=None, max_log_bytes=32000):
        self.sandbox = SandboxRunner(workspace=workspace, limits=SandboxLimits(timeout_seconds=timeout))
        self.argv = tuple(str(arg).replace("{port}", str(port)) for arg in argv)
        self.port = int(port)
        if not 1 <= self.port <= 65535 or not self.argv:
            raise ValueError("A local port and non-empty argv are required")
        self.timeout = min(max(float(timeout), .1), 60)
        self.cancel = cancel if cancel is not None else ACTIVE_CANCELLATION.get()
        self.max_log_bytes = max_log_bytes
        self.logs = deque()
        self.log_bytes = 0
        self.process = None
        self.reader = None
        self.stopped = False
        self.deadline = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def start(self):
        if self.process is not None:
            raise RuntimeError("ManagedProcess instances cannot be started twice")
        self.deadline = time.monotonic() + self.timeout
        # Refuse to probe or stop a service that belongs to somebody else.
        with socket.socket() as port_check:
            port_check.bind(("127.0.0.1", self.port))
        self.sandbox.home_dir.mkdir(parents=True, exist_ok=True)
        self.sandbox.temp_dir.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen(self.argv, cwd=self.sandbox.workspace,
            env=self.sandbox._build_environment(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
            preexec_fn=self.sandbox._build_preexec_fn())
        self.reader = threading.Thread(target=self._drain, daemon=True)
        try:
            self.reader.start()
        except Exception:
            self.stop()
            raise
        return self

    def _drain(self):
        while True:
            chunk = self.process.stdout.read(1024)
            if not chunk:
                return
            self.logs.append(chunk)
            self.log_bytes += len(chunk)
            while self.log_bytes > self.max_log_bytes and self.logs:
                self.log_bytes -= len(self.logs.popleft())

    def _check(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError("Service lifecycle deadline exceeded")
        if self.cancel is not None and (self.cancel.is_set() if hasattr(self.cancel, "is_set") else self.cancel.is_cancelled):
            raise InterruptedError("Service validation cancelled")
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("Service exited before validation finished")

    def probe(self, path="/", *, timeout=.5, method="GET", json_body=None):
        self._check()
        if not path.startswith("/") or path.startswith("//") or "\r" in path or "\n" in path:
            raise ValueError("Probe must be a local absolute URL path")
        # Redirects must not escape this owned local service.
        from urllib.request import HTTPRedirectHandler, build_opener, Request
        from urllib.error import HTTPError
        import json
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
            raise ValueError("Unsupported HTTP method")
        request = Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                          data=json.dumps(json_body).encode() if json_body is not None else None,
                          headers={"Content-Type": "application/json"} if json_body is not None else {})
        try:
            response = build_opener(NoRedirect).open(request, timeout=timeout)
        except HTTPError as error:
            response = error
        with response:
            chunks, remaining = [], 65536
            while remaining:
                self._check()
                chunk = response.read1(min(4096, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            return response.status, b"".join(chunks).decode("utf-8", errors="replace")

    def wait_ready(self, path="/"):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self._check()
            try:
                self.probe(path)
                return
            except (OSError, TimeoutError):
                time.sleep(.03)
        raise TimeoutError("Service readiness deadline exceeded")

    def stop(self):
        if self.process is None or self.stopped:
            return
        self.stopped = True
        # Kill the owned group even if the parent exited and left children behind.
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.process.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # The group may have disappeared between wait() and killpg(), or
            # macOS may briefly report EPERM while reaping the session. The
            # best-effort hard kill must never replace the original service
            # timeout/validation error during context-manager cleanup.
            pass
        self.process.wait(timeout=2)
        if self.reader and self.reader.ident is not None:
            self.reader.join(timeout=1)
        self.process.stdout.close()

    @property
    def output(self):
        return b"".join(tuple(self.logs)).decode("utf-8", errors="replace")
