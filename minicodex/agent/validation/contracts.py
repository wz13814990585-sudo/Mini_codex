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
class BrowserNoOpBehavior:
    action: BrowserAction
    assertion: BrowserAssertion


@dataclass(frozen=True)
class BrowserInteractionContract:
    path: str
    action: BrowserAction
    assertion: BrowserAssertion
    non_target: BrowserNoOpBehavior | None = None
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
        _exact(raw, {"type", "path", "action", "assertion"}, optional={"non_target"})
        action = _browser_action(raw["action"])
        assertion = _browser_assertion(raw["assertion"])
        non_target = raw.get("non_target")
        no_op = None
        if non_target is not None:
            if not isinstance(non_target, dict):
                raise ValueError("non_target 必须是对象")
            _exact(non_target, {"action", "assertion"})
            no_op = BrowserNoOpBehavior(
                _browser_action(non_target["action"]),
                _browser_assertion(non_target["assertion"]),
            )
        return BrowserInteractionContract(
            _text(raw, "path"),
            action,
            assertion,
            no_op,
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


def _browser_action(raw: Any) -> BrowserAction:
    if not isinstance(raw, dict):
        raise ValueError("browser action 必须是对象")
    _exact(raw, {"type"}, optional={"selector", "value"})
    action_type = _text(raw, "type")
    if action_type not in {"click", "keypress"}:
        raise ValueError("browser action 无效")
    selector = str(raw.get("selector", "")).strip()
    value = str(raw.get("value", "")).strip()
    if action_type == "click" and not selector:
        raise ValueError("click 需要 selector")
    if action_type == "keypress" and not value:
        raise ValueError("keypress 需要 value")
    return BrowserAction(action_type, selector, value)


def _browser_assertion(raw: Any) -> BrowserAssertion:
    if not isinstance(raw, dict):
        raise ValueError("browser assertion 必须是对象")
    _exact(raw, {"type", "selector", "value"})
    assertion_type = _text(raw, "type")
    if assertion_type != "text_equals":
        raise ValueError("browser assertion 无效")
    return BrowserAssertion(
        assertion_type,
        _text(raw, "selector"),
        _text(raw, "value"),
    )


def _exact(raw: dict, required: set[str], *, optional: set[str] | None = None) -> None:
    optional = optional or set()
    if set(raw) - required - optional or required - set(raw):
        raise ValueError("contract 字段无效")
