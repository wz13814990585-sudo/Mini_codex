"""Typed, tool-independent machine contracts for required validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FileExistsContract:
    path: str
    contract_type: str = "file_exists"


@dataclass(frozen=True)
class FileContainsContract:
    path: str
    text: str
    contract_type: str = "file_contains"


@dataclass(frozen=True)
class TestTargetContract:
    __test__ = False
    target: str
    contract_type: str = "pytest"


@dataclass(frozen=True)
class CommandContract:
    command: str
    contract_type: str = "command"


@dataclass(frozen=True)
class PythonBehaviorContract:
    code: str
    contract_type: str = "python_behavior"


@dataclass(frozen=True)
class NodeBehaviorContract:
    code: str
    contract_type: str = "node_behavior"


@dataclass(frozen=True)
class HttpContract:
    method: str
    path: str
    expected_status: int
    expected_text: str = ""
    json_body: dict | None = None
    contract_type: str = "http_response"


@dataclass(frozen=True)
class BrowserAction:
    type: str
    selector: str = ""
    value: str = ""


@dataclass(frozen=True)
class BrowserAssertion:
    type: str
    selector: str
    value: str


@dataclass(frozen=True)
class BrowserInteractionContract:
    path: str
    action: BrowserAction
    assertion: BrowserAssertion
    contract_type: str = "browser_interaction"


@dataclass(frozen=True)
class SemanticContract:
    path: str
    claim: str
    contract_type: str = "semantic"


VerificationContract = (
    FileExistsContract
    | FileContainsContract
    | TestTargetContract
    | CommandContract
    | PythonBehaviorContract
    | NodeBehaviorContract
    | HttpContract
    | BrowserInteractionContract
    | SemanticContract
)


def parse_contract(raw: Any) -> VerificationContract:
    """Strictly normalize one tagged contract without inferring from prose."""

    if not isinstance(raw, dict):
        raise ValueError("contract 必须是对象")
    kind = str(raw.get("type", "")).strip().lower()
    if kind == "file_exists":
        _exact(raw, {"type", "path"})
        return FileExistsContract(_text(raw, "path"))
    if kind == "file_contains":
        _exact(raw, {"type", "path", "text"})
        return FileContainsContract(_text(raw, "path"), _text(raw, "text"))
    if kind == "pytest":
        _exact(raw, {"type", "target"})
        return TestTargetContract(_text(raw, "target"))
    if kind == "command":
        _exact(raw, {"type", "command"})
        return CommandContract(_text(raw, "command"))
    if kind == "python_behavior":
        _exact(raw, {"type", "code"})
        return PythonBehaviorContract(_text(raw, "code"))
    if kind == "node_behavior":
        _exact(raw, {"type", "code"})
        return NodeBehaviorContract(_text(raw, "code"))
    if kind == "http_response":
        _exact(raw, {"type", "method", "path", "expected_status"},
               optional={"expected_text", "json_body"})
        method = _text(raw, "method").upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("HTTP method 无效")
        status = raw["expected_status"]
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
            raise ValueError("expected_status 无效")
        body = raw.get("json_body")
        if body is not None and not isinstance(body, dict):
            raise ValueError("json_body 必须是对象")
        return HttpContract(method, _text(raw, "path"), status,
                            str(raw.get("expected_text", "")), body)
    if kind == "browser_interaction":
        _exact(raw, {"type", "path", "action", "assertion"})
        action = raw["action"]
        assertion = raw["assertion"]
        if not isinstance(action, dict) or not isinstance(assertion, dict):
            raise ValueError("action/assertion 必须是对象")
        _exact(action, {"type"}, optional={"selector", "value"})
        _exact(assertion, {"type", "selector", "value"})
        action_type = _text(action, "type")
        if action_type not in {"click", "keypress"}:
            raise ValueError("browser action 无效")
        assertion_type = _text(assertion, "type")
        if assertion_type != "text_equals":
            raise ValueError("browser assertion 无效")
        selector = str(action.get("selector", "")).strip()
        value = str(action.get("value", "")).strip()
        if action_type == "click" and not selector:
            raise ValueError("click 需要 selector")
        if action_type == "keypress" and not value:
            raise ValueError("keypress 需要 value")
        return BrowserInteractionContract(
            _text(raw, "path"),
            BrowserAction(action_type, selector, value),
            BrowserAssertion(assertion_type, _text(assertion, "selector"),
                             _text(assertion, "value")),
        )
    if kind == "semantic":
        _exact(raw, {"type", "path", "claim"})
        return SemanticContract(_text(raw, "path"), _text(raw, "claim"))
    raise ValueError(f"不支持的 contract type：{kind or '<empty>'}")


def contract_key(contract: VerificationContract) -> tuple:
    """Stable equality key used to merge explicitly identical obligations."""

    return (type(contract).__name__, repr(contract))


def _text(raw: dict, key: str) -> str:
    value = str(raw.get(key, "")).strip()
    if not value:
        raise ValueError(f"{key} 不能为空")
    return value


def _exact(raw: dict, required: set[str], *, optional: set[str] | None = None) -> None:
    optional = optional or set()
    if set(raw) - required - optional or required - set(raw):
        raise ValueError("contract 字段无效")
