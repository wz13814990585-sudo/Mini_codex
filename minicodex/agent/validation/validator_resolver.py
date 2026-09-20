"""Resolve typed contracts to one registered deterministic validator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from html.parser import HTMLParser
import json
import os
from pathlib import Path
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


class _BrowserHtmlStateParser(HTMLParser):
    """Extract external script and initial textContent for id-addressable nodes."""

    _VOID_TAGS = frozenset({
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.initial_text: dict[str, str] = {}
        self.script_src = ""
        self._tag_stack: list[str] = []
        self._text_contexts: list[tuple[str, int]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        attributes = {str(name).casefold(): value or "" for name, value in attrs}
        if tag == "script" and not self.script_src and attributes.get("src"):
            self.script_src = attributes["src"]

        selector = f"#{attributes['id']}" if attributes.get("id") else ""
        if tag in self._VOID_TAGS:
            if selector:
                self.initial_text.setdefault(selector, "")
            return

        self._tag_stack.append(tag)
        if selector and selector not in self.initial_text:
            self.initial_text[selector] = ""
            self._text_contexts.append((selector, len(self._tag_stack)))

    def handle_startendtag(self, tag: str, attrs) -> None:
        attributes = {str(name).casefold(): value or "" for name, value in attrs}
        if attributes.get("id"):
            self.initial_text.setdefault(f"#{attributes['id']}", "")

    def handle_data(self, data: str) -> None:
        for selector, _depth in self._text_contexts:
            self.initial_text[selector] += data

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        try:
            index = len(self._tag_stack) - 1 - self._tag_stack[::-1].index(tag)
        except ValueError:
            return
        closing_depth = index + 1
        self._text_contexts = [
            context for context in self._text_contexts
            if context[1] < closing_depth
        ]
        del self._tag_stack[index:]


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
            if self._http_requires_json_body(contract):
                return self._unresolved(
                    check, ResolutionStatus.TARGET_UNRESOLVED,
                    "认证类 HTTP 契约缺少 json_body；不能用空请求体验收登录或凭据结果。",
                )
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
            if contract.non_target is not None and (
                not contract.non_target.assertion.selector
                or contract.non_target.assertion.type != "text_equals"
                or contract.non_target.assertion.value == ""
            ):
                return self._unresolved(
                    check, ResolutionStatus.TARGET_UNRESOLVED,
                    "浏览器非目标行为缺少精确的不变状态断言。",
                )
            browser = self._first(registry, "validation.browser")
            browser_path = self._browser_document_path(contract.path)
            if browser and browser_path:
                action = (
                    {"click_selector": contract.action.selector}
                    if contract.action.type == "click"
                    else {"keypress": contract.action.value,
                          "keypress_selector": contract.action.selector or contract.assertion.selector}
                )
                non_target = {}
                if contract.non_target is not None:
                    non_target = {
                        "non_target_action_type": contract.non_target.action.type,
                        "non_target_action_selector": contract.non_target.action.selector,
                        "non_target_action_value": contract.non_target.action.value,
                        "non_target_assertion_selector": contract.non_target.assertion.selector,
                        "non_target_expected_value": contract.non_target.assertion.value,
                    }
                return self._result(
                    check, browser, "validation.browser",
                    {**common, "path": browser_path,
                     "selector": contract.assertion.selector,
                     "assertion_kind": "text",
                     "expected_value": contract.assertion.value,
                     "expected_text": contract.assertion.value,
                     **action, **non_target},
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

    def _python_command(self, code: str) -> str:
        # Align with oracle pytest env so src-layout packages import at workspace root.
        pythonpath = os.pathsep.join(
            filter(
                None,
                (
                    str(self.workspace / "src"),
                    str(self.workspace),
                    os.environ.get("PYTHONPATH", ""),
                ),
            )
        )
        return (
            f"PYTHONPATH={shlex.quote(pythonpath)} "
            f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
        )

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

    @staticmethod
    def _http_requires_json_body(contract: HttpContract) -> bool:
        """Auth-like mutating requests must carry an explicit body to avoid empty-body thrash."""

        if contract.json_body is not None:
            return False
        if contract.method not in {"POST", "PUT", "PATCH"}:
            return False
        path = contract.path.casefold()
        return any(
            token in path
            for token in (
                "/login", "/auth", "/signin", "/sign-in",
                "/signup", "/sign-up", "/register", "/token",
            )
        )

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
        json_kw = (
            "" if contract.json_body is None
            else f",json={contract.json_body!r}"
        )
        if "FastAPI" in source:
            code = (
                f"from importlib import import_module; "
                f"from fastapi.testclient import TestClient; "
                f"app=getattr(import_module({module!r}),'app'); "
                f"r=TestClient(app).request({contract.method!r},{contract.path!r}{json_kw}); "
                f"assert r.status_code=={contract.expected_status}"
            )
        elif "Flask" in source:
            code = (
                f"from importlib import import_module; "
                f"app=getattr(import_module({module!r}),'app'); "
                f"r=app.test_client().open({contract.path!r},method={contract.method!r}{json_kw}); "
                f"assert r.status_code=={contract.expected_status}"
            )
        else:
            return ""
        if contract.expected_text:
            if "FastAPI" in source:
                code += f"; assert {contract.expected_text!r} in r.text"
            else:
                code += f"; assert {contract.expected_text!r} in r.get_data(as_text=True)"
        return self._python_command(code)

    def _browser_node_command(self, contract: BrowserInteractionContract) -> str:
        if contract.action.type not in {"click", "keypress"}:
            return ""
        script_path = contract.path
        initial_text: dict[str, str] = {}
        if contract.path.endswith(".html"):
            try:
                html = (self.workspace / contract.path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                return ""
            parser = _BrowserHtmlStateParser()
            parser.feed(html)
            parser.close()
            if not parser.script_src:
                return ""
            initial_text = parser.initial_text
            script_path = str((Path(contract.path).parent / parser.script_src).as_posix())
            while script_path.startswith("./"):
                script_path = script_path[2:]
        else:
            document = self._html_document_for_script(contract.path)
            if document is not None:
                initial_text = document.initial_text
        action_selector = contract.action.selector or contract.assertion.selector
        non_target_script = ""
        if contract.non_target is not None:
            non_target_selector = (
                contract.non_target.action.selector
                or contract.non_target.assertion.selector
            )
            non_target_script = (
                f"perform({json.dumps(contract.non_target.action.type)}, "
                f"{json.dumps(non_target_selector)}, "
                f"{json.dumps(contract.non_target.action.value)}, 24);\n"
                f"assertText({json.dumps(contract.non_target.assertion.selector)}, "
                f"{json.dumps(contract.non_target.assertion.value)}, 25);"
            )
        script = f"""
import {{readFileSync}} from 'node:fs';
const initialText = {json.dumps(initial_text)};
const nodes = new Map();
const node = selector => {{
  if (!nodes.has(selector)) nodes.set(selector, {{
    textContent: Object.prototype.hasOwnProperty.call(initialText, selector) ? initialText[selector] : '',
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
const perform = (type, selector, value, missingCode) => {{
  const target = node(selector);
  const cb = type === 'click'
    ? (target._listeners?.click || target.onclick)
    : (documentListeners.keydown || target._listeners?.keydown);
  if (typeof cb !== 'function') {{
    console.error(
      'Missing ' + type + ' handler on ' + selector
      + '; fix the referenced script (for example app.js). '
      + 'Do not replace browser proof with validate_static_web/require_inline_script.'
    );
    process.exit(missingCode);
  }}
  cb(type === 'click' ? {{type:'click'}} : {{type:'keydown', key:value}});
}};
const assertText = (selector, expected, failureCode) => {{
  if (node(selector).textContent !== expected) {{
    console.error(
      'Assertion failed for ' + selector + ': expected ' + JSON.stringify(expected)
      + ', got ' + JSON.stringify(node(selector).textContent)
    );
    process.exit(failureCode);
  }}
}};
{non_target_script}
perform({json.dumps(contract.action.type)}, {json.dumps(action_selector)}, {json.dumps(contract.action.value)}, 21);
assertText({json.dumps(contract.assertion.selector)}, {json.dumps(contract.assertion.value)}, 23);
"""
        return f"node --input-type=module -e {shlex.quote(script)}"

    def _html_document_for_script(self, script_path: str) -> _BrowserHtmlStateParser | None:
        match = self._html_document_match(script_path)
        return match[1] if match is not None else None

    def _browser_document_path(self, contract_path: str) -> str:
        if contract_path.casefold().endswith(".html"):
            return contract_path
        match = self._html_document_match(contract_path)
        return match[0] if match is not None else ""

    def _html_document_match(
        self, script_path: str,
    ) -> tuple[str, _BrowserHtmlStateParser] | None:
        try:
            expected = (self.workspace / script_path).resolve()
            expected.relative_to(self.workspace)
        except (OSError, ValueError):
            return None
        for html_path in sorted(self.workspace.rglob("*.html")):
            try:
                parser = _BrowserHtmlStateParser()
                parser.feed(html_path.read_text(encoding="utf-8"))
                parser.close()
                if not parser.script_src:
                    continue
                referenced = (html_path.parent / parser.script_src).resolve()
                referenced.relative_to(self.workspace)
            except (OSError, UnicodeError, ValueError):
                continue
            if referenced == expected:
                return html_path.relative_to(self.workspace).as_posix(), parser
        return None
