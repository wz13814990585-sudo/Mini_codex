"""Run and probe a local application, always cleaning up the owned process group."""
from pathlib import Path
import json
import re
import shlex
import socket

from ..base import BaseTool
from ..results import ToolResult
from ...agent.runtime.managed_process import ManagedProcess
from ...agent.safety.safety import SafetyPolicy


class ValidateServiceTool(BaseTool):
    name = "validate_service"
    capabilities = frozenset({"service.validate"})
    description = (
        "启动有时限的本地服务，等待就绪，断言 HTTP 响应，"
        "然后停止所有由本工具持有的进程。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "argv": {
                "type": "array",
                "items": {"type": "string"},
                "description": "启动服务的命令参数列表。",
            },
            "port": {
                "type": "integer",
                "description": "服务监听端口；0 表示自动分配。",
            },
            "path": {
                "type": "string",
                "description": "用于断言的 HTTP 路径。",
            },
            "expected_text": {
                "type": "string",
                "description": "响应体中必须包含的文本。",
            },
            "timeout": {
                "type": "number",
                "description": "等待就绪与探测的超时秒数。",
            },
            "expected_status": {
                "type": "integer",
                "description": "期望的 HTTP 状态码；默认 200。",
            },
            "ready_path": {
                "type": "string",
                "description": "可选的就绪探测路径；默认与 path 相同。",
            },
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
                "description": "HTTP 请求方法。",
            },
            "json_body": {
                "type": "object",
                "description": "可选的 JSON 请求体。",
            },
        },
        "required": ["argv", "port", "path", "expected_text"],
    }

    def __init__(self, workspace="."):
        self.workspace = Path(workspace).resolve()

    def execute(self, argv, port, path, expected_text, timeout=15, expected_status=None,
                ready_path=None, method="GET", json_body=None):
        policy = SafetyPolicy(workspace=self.workspace)
        decision = policy.assess("run_command", {"command": shlex.join(argv)})
        if not decision.allowed:
            return ToolResult(False, "服务命令被安全策略拦截", {"failure_type": "safety_blocked"}, error=decision.reason)
        if not expected_text and expected_status is None:
            return ToolResult(False, "需要可观察的响应断言", {})
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
                passed = (
                    status == (200 if expected_status is None else int(expected_status))
                    and self._response_contains(body, expected_text)
                )
            return ToolResult(True, "服务断言通过" if passed else "服务断言失败",
                              {"outcome": "passed" if passed else "failed", "errors": [] if passed else ["response mismatch"],
                               "path": path, "status": status, "stdout": service.output})
        except (OSError, RuntimeError, TimeoutError, InterruptedError, ValueError) as exc:
            service.stop()
            return ToolResult(False, "无法验证服务",
                              {"failure_type": "environment_failure", "stdout": service.output}, error=str(exc))

    @staticmethod
    def _response_contains(body: str, expected_text: str) -> bool:
        if expected_text in body:
            return True
        # JSON producers legitimately differ only in insignificant formatting
        # (for example {"status":"ok"} vs {"status": "ok"}).  Relax
        # whitespace only for a JSON response and a JSON-shaped expectation;
        # ordinary human-readable text remains an exact substring assertion.
        if not any(token in expected_text for token in (":", "{", "[")):
            return False
        try:
            json.loads(body)
        except (TypeError, json.JSONDecodeError):
            return False
        compact = lambda value: re.sub(r"\s+", "", value)
        return compact(expected_text) in compact(body)
