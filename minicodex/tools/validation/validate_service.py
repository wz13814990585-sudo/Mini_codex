"""Run and probe a local application, always cleaning up the owned process group."""
from pathlib import Path
import shlex
import socket

from ..base import BaseTool
from ..results import ToolResult
from ...agent.runtime.managed_process import ManagedProcess
from ...agent.safety.safety import SafetyPolicy


class ValidateServiceTool(BaseTool):
    name = "validate_service"
    capabilities = frozenset({"service.validate"})
    description = "Start a bounded local service, wait ready, assert an HTTP response, and stop all owned processes."
    parameters = {"type": "object", "properties": {
        "argv": {"type": "array", "items": {"type": "string"}},
        "port": {"type": "integer"}, "path": {"type": "string"},
        "expected_text": {"type": "string"}, "timeout": {"type": "number"},
        "expected_status": {"type": "integer"}, "ready_path": {"type": "string"},
        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]},
        "json_body": {"type": "object"},
    }, "required": ["argv", "port", "path", "expected_text"]}

    def __init__(self, workspace="."):
        self.workspace = Path(workspace).resolve()

    def execute(self, argv, port, path, expected_text, timeout=15, expected_status=None,
                ready_path=None, method="GET", json_body=None):
        policy = SafetyPolicy(workspace=self.workspace)
        decision = policy.assess("run_command", {"command": shlex.join(argv)})
        if not decision.allowed:
            return ToolResult(False, "Service command blocked", {"failure_type": "safety_blocked"}, error=decision.reason)
        if not expected_text and expected_status is None:
            return ToolResult(False, "An observable response assertion is required", {})
        if int(port) == 0:
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
        argv = [str(part).replace("{port}", str(port)) for part in argv]
        service = ManagedProcess(self.workspace, argv, port=port, timeout=timeout)
        try:
            with service:
                service.wait_ready(ready_path or path)
                status, body = service.probe(path, method=method, json_body=json_body)
                passed = status == (200 if expected_status is None else int(expected_status)) and expected_text in body
            return ToolResult(True, "Service assertion passed" if passed else "Service assertion failed",
                              {"outcome": "passed" if passed else "failed", "errors": [] if passed else ["response mismatch"],
                               "path": path, "status": status, "stdout": service.output})
        except (OSError, RuntimeError, TimeoutError, InterruptedError, ValueError) as exc:
            service.stop()
            return ToolResult(False, "Service could not be validated",
                              {"failure_type": "environment_failure", "stdout": service.output}, error=str(exc))
