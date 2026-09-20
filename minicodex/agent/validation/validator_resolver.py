"""Resolve typed contracts to one registered deterministic validator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import re
import shlex
import sys

from .contracts import (
    BrowserInteractionContract,
    CommandContract,
    FileContainsContract,
    FileExistsContract,
    HttpContract,
    NodeBehaviorContract,
    PythonBehaviorContract,
    SemanticContract,
    TestTargetContract,
)
from .plan import ValidationCheck


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    CAPABILITY_MISSING = "capability_missing"
    TARGET_UNRESOLVED = "target_unresolved"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ValidatorResolution:
    check_id: str
    status: ResolutionStatus
    tool_name: str = ""
    arguments: dict = field(default_factory=dict)
    capability: str = ""
    target: str = ""
    validation_key: str = ""
    reason: str = ""


class ValidatorResolver:
    """Capability-aware contract dispatch with no natural-language parsing."""

    def __init__(self, workspace: str | Path = ".", *, test_index=None) -> None:
        del test_index
        self.workspace = Path(workspace).resolve()

    def resolve(self, check: ValidationCheck, *, registry, profile=None, paths=(), revision=0):
        del revision
        contract = check.contract
        common = {"purpose": check.purpose.value, "validation_check": check.id}

        if isinstance(contract, FileExistsContract):
            command = self._python_command(
                f"from pathlib import Path; assert Path({contract.path!r}).is_file()"
            )
            return self._tool(registry, check, "process.run", "run_command",
                              {**common, "command": command}, contract.path)

        if isinstance(contract, FileContainsContract):
            command = self._python_command(
                f"from pathlib import Path; assert {contract.text!r} in Path({contract.path!r}).read_text(encoding='utf-8')"
            )
            return self._tool(registry, check, "process.run", "run_command",
                              {**common, "command": command}, contract.path)

        if isinstance(contract, TestTargetContract):
            target = contract.target
            if not (self.workspace / target.split("::", 1)[0]).exists():
                return self._unresolved(check, ResolutionStatus.TARGET_UNRESOLVED,
                                        f"测试目标不存在：{target}")
            return self._tool(registry, check, "test.run", "run_tests",
                              {**common, "path": target}, target)

        if isinstance(contract, CommandContract):
            return self._tool(registry, check, "process.run", "run_command",
                              {**common, "command": contract.command}, contract.command)

        if isinstance(contract, PythonBehaviorContract):
            command = self._python_command(contract.code)
            return self._tool(registry, check, "process.run", "run_command",
                              {**common, "command": command}, contract.code)

        if isinstance(contract, NodeBehaviorContract):
            command = f"node --input-type=module -e {shlex.quote(contract.code)}"
            return self._tool(registry, check, "process.run", "run_command",
                              {**common, "command": command}, contract.code)

        if isinstance(contract, HttpContract):
            service = self._service_arguments(contract, profile)
            if service is not None and self._first(registry, "service.validate"):
                return self._tool(registry, check, "service.validate", "validate_service",
                                  {**common, **service}, f"{contract.method} {contract.path}")
            command = self._http_inprocess_command(contract, paths)
            if command:
                return self._tool(
                    registry, check, "process.run", "run_command",
                    {**common, "command": command}, f"{contract.method} {contract.path}",
                )
            return self._unresolved(
                check, ResolutionStatus.TARGET_UNRESOLVED,
                "HTTP 契约既无安全服务启动命令，也无可解析的应用模块。",
            )

        if isinstance(contract, BrowserInteractionContract):
            if (
                not contract.path
                or not contract.assertion.selector
                or contract.assertion.type != "text_equals"
                or contract.assertion.value == ""
            ):
                return self._unresolved(
                    check, ResolutionStatus.TARGET_UNRESOLVED,
                    "浏览器交互契约缺少操作后的精确文本断言。",
                )
            browser = self._first(registry, "validation.browser")
            if browser:
                action = (
                    {"click_selector": contract.action.selector}
                    if contract.action.type == "click"
                    else {"keypress": contract.action.value,
                          "keypress_selector": contract.action.selector or contract.assertion.selector}
                )
                return self._result(
                    check, browser, "validation.browser",
                    {**common, "path": contract.path,
                     "selector": contract.assertion.selector,
                     "assertion_kind": "text",
                     "expected_value": contract.assertion.value,
                     "expected_text": contract.assertion.value, **action},
                    contract.path,
                )
            command = self._browser_node_command(contract)
            if command and self._first(registry, "process.run"):
                return self._tool(registry, check, "process.run", "run_command",
                                  {**common, "command": command}, contract.path)
            return self._unresolved(
                check, ResolutionStatus.CAPABILITY_MISSING,
                "浏览器能力不可用，且契约不支持确定性 Node DOM 回退。",
            )

        if isinstance(contract, SemanticContract):
            if not contract.path:
                return self._unresolved(check, ResolutionStatus.TARGET_UNRESOLVED,
                                        "语义契约缺少目标路径。")
            return self._tool(registry, check, "validation.semantic", "validate_semantic",
                              {**common, "path": contract.path, "claim": contract.claim},
                              contract.path)

        return self._unresolved(check, ResolutionStatus.UNSUPPORTED, "不支持的验证契约。")

    def _tool(self, registry, check, capability, preferred_name, arguments, target):
        tool_name = self._first(registry, capability)
        if not tool_name:
            return self._unresolved(check, ResolutionStatus.CAPABILITY_MISSING,
                                    f"所需能力 {capability} 不可用。")
        return self._result(check, tool_name or preferred_name, capability, arguments, target)

    @staticmethod
    def _first(registry, capability):
        finder = getattr(registry, "tool_names_for_capability", None)
        if callable(finder):
            return next(iter(finder(capability)), "")
        return next((
            name for name in getattr(registry, "_tools", {})
            if capability in registry.capabilities_for(name)
        ), "")

    @staticmethod
    def _result(check, tool_name, capability, arguments, target):
        key = f"{check.contract_type}|{target}"
        return ValidatorResolution(
            check.id, ResolutionStatus.RESOLVED, tool_name, arguments,
            capability, target, key, "类型化契约已确定解析。",
        )

    @staticmethod
    def _unresolved(check, status, reason):
        return ValidatorResolution(check.id, status, reason=reason)

    @staticmethod
    def _python_command(code: str) -> str:
        return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"

    @staticmethod
    def _service_arguments(contract: HttpContract, profile):
        commands = dict(getattr(profile, "commands", ()) or ())
        command = commands.get("start") or commands.get("dev")
        if not command or "{port}" not in command:
            return None
        try:
            argv = shlex.split(command)
        except ValueError:
            return None
        result = {
            "argv": argv, "port": 0, "path": contract.path,
            "method": contract.method, "expected_status": contract.expected_status,
            "expected_text": contract.expected_text,
        }
        if contract.json_body is not None:
            result["json_body"] = contract.json_body
        return result

    def _http_inprocess_command(self, contract: HttpContract, paths) -> str:
        candidates = tuple(dict.fromkeys((*paths, "app.py")))
        source_path = next((
            path for path in candidates
            if str(path).endswith(".py") and (self.workspace / str(path)).is_file()
        ), "")
        if not source_path:
            return ""
        try:
            source = (self.workspace / source_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""
        module = str(source_path)[:-3].replace("/", ".")
        body = repr(contract.json_body)
        if "FastAPI" in source:
            code = (
                f"from importlib import import_module; "
                f"from fastapi.testclient import TestClient; "
                f"app=getattr(import_module({module!r}),'app'); "
                f"r=TestClient(app).request({contract.method!r},{contract.path!r},json={body}); "
                f"assert r.status_code=={contract.expected_status}"
            )
        elif "Flask" in source:
            code = (
                f"from importlib import import_module; "
                f"app=getattr(import_module({module!r}),'app'); "
                f"r=app.test_client().open({contract.path!r},method={contract.method!r},json={body}); "
                f"assert r.status_code=={contract.expected_status}"
            )
        else:
            return ""
        if contract.expected_text:
            code += f"; assert {contract.expected_text!r} in r.get_data(as_text=True)"
        return self._python_command(code)

    def _browser_node_command(self, contract: BrowserInteractionContract) -> str:
        if contract.action.type not in {"click", "keypress"}:
            return ""
        script_path = contract.path
        if contract.path.endswith(".html"):
            try:
                html = (self.workspace / contract.path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                return ""
            match = re.search(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, re.I)
            if not match:
                return ""
            script_path = str((Path(contract.path).parent / match.group(1)).as_posix())
            while script_path.startswith("./"):
                script_path = script_path[2:]
        action_selector = contract.action.selector or contract.assertion.selector
        script = f"""
import {{readFileSync}} from 'node:fs';
const nodes = new Map();
const node = selector => {{
  if (!nodes.has(selector)) nodes.set(selector, {{
    textContent: selector === {json.dumps(contract.assertion.selector)} ? '' : '',
    addEventListener: (type, cb) => {{ nodes.get(selector)._listeners ??= {{}}; nodes.get(selector)._listeners[type] = cb; }}
  }});
  return nodes.get(selector);
}};
const documentListeners = {{}};
globalThis.document = {{
  querySelector: node,
  getElementById: id => node('#' + id),
  addEventListener: (type, cb) => documentListeners[type] = cb
}};
const source = readFileSync({json.dumps(script_path)}, 'utf8');
await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const action = node({json.dumps(action_selector)});
if ({json.dumps(contract.action.type)} === 'click') {{
  const cb = action._listeners?.click || action.onclick;
  if (typeof cb !== 'function') process.exit(21);
  cb({{type:'click'}});
}} else {{
  const cb = documentListeners.keydown || action._listeners?.keydown;
  if (typeof cb !== 'function') process.exit(22);
  cb({{key:{json.dumps(contract.action.value)}}});
}}
if (node({json.dumps(contract.assertion.selector)}).textContent !== {json.dumps(contract.assertion.value)}) process.exit(23);
"""
        return f"node --input-type=module -e {shlex.quote(script)}"
