"""Resolve one missing proof obligation to a registered validator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
import shlex

from .plan import EvidenceStrength, ValidationCheck
from .test_target_resolver import TestTargetResolver
from .verification_spec import (BrowserVerificationSpec, CommandVerificationSpec, FileVerificationSpec,
                                HttpVerificationSpec, SemanticVerificationSpec, TestVerificationSpec)


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    CAPABILITY_MISSING = "capability_missing"
    TARGET_UNRESOLVED = "target_unresolved"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ValidatorResolution:
    check_id: str
    tool_name: str = ""
    arguments: dict = None
    reason: str = ""
    status: ResolutionStatus = ResolutionStatus.RESOLVED

    def __post_init__(self):
        object.__setattr__(self, "arguments", self.arguments or {})


class ValidatorResolver:
    """Capability-first, bounded resolution; it never invents a different check."""

    def __init__(self, workspace: str | Path = ".", *, test_index=None) -> None:
        self.test_target_resolver = TestTargetResolver(workspace, test_index=test_index)

    def resolve(self, check: ValidationCheck, *, registry, profile=None, paths=(), revision=0):
        candidates = self._tools_by_capability(registry)
        check_paths = tuple(dict.fromkeys((*paths, *self._paths_from_observable(check.observable))))
        common = {"purpose": check.purpose.value, "validation_check": check.id}
        spec = check.spec
        if isinstance(spec, TestVerificationSpec):
            if not spec.test_target or not self.test_target_resolver._exists(spec.test_target):
                return self._unresolved(check, ResolutionStatus.TARGET_UNRESOLVED,
                                        "绑定的聚焦测试目标在本工作区版本中缺失或已过期。")
            return self._resolve_capability(candidates, "test.run", check, common,
                                            {"path": spec.test_target},
                                            "绑定器选定的 TestVerificationSpec 即为精确测试目标。")
        if isinstance(spec, CommandVerificationSpec):
            return self._resolve_capability(candidates, "process.run", check, common,
                                            {"command": spec.command}, "规格已绑定配置的命令。")
        if isinstance(spec, HttpVerificationSpec):
            service = self._service_arguments_from_spec(spec, profile)
            if service is None:
                return self._unresolved(check, ResolutionStatus.TARGET_UNRESOLVED,
                                        "HTTP 证明需要包含 {port} 的安全 profile start/dev 命令。")
            return self._resolve_capability(candidates, "service.validate", check, common, service,
                                            "类型化 HTTP 契约提供了方法、路径与期望状态码。")
        if isinstance(spec, BrowserVerificationSpec):
            assertion_kind = spec.assertion_kind or ("text" if spec.expected_text else "")
            assertion_target = spec.assertion_target or spec.selector
            expected_value = spec.expected_value or spec.expected_text
            if not spec.action or not spec.selector or not assertion_kind or not assertion_target or not expected_value:
                return self._unresolved(check, ResolutionStatus.TARGET_UNRESOLVED,
                                        "交互式浏览器证明需要操作、选择器以及操作后断言。")
            action_args = ({"keypress": spec.value, "keypress_selector": spec.selector}
                           if spec.action == "keypress" else {"click_selector": spec.selector})
            return self._resolve_capability(candidates, "validation.browser", check, common,
                                            {"path": spec.path, "selector": assertion_target,
                                             "expected_text": spec.expected_text,
                                             "assertion_kind": assertion_kind,
                                             "expected_value": expected_value, **action_args},
                                            "类型化浏览器交互定义了精确断言。")
        if isinstance(spec, FileVerificationSpec):
            name = self._first(candidates, "validation.static_web") if spec.path.endswith(".html") else None
            if name:
                return self._result(name, {**common, "path": spec.path, "expected_text": spec.contains}, check,
                                    "文件规格映射到静态验证。")
        if isinstance(spec, SemanticVerificationSpec):
            return self._resolve_capability(candidates, "validation.semantic", check, common,
                                            {"path": spec.path, "claim": spec.claim},
                                            "语义声明需要语义验证器。")
        if check.capability == "process.run" and check.target:
            return self._resolve_capability(candidates, "process.run", check, common,
                                            {"command": check.target}, "计划提供了精确配置的命令。")
        if check.capability == "validation.browser":
            if not self._first(candidates, "validation.browser"):
                return self._unresolved(check, ResolutionStatus.CAPABILITY_MISSING,
                                        "所需能力 validation.browser 不可用。")
            return self._unresolved(check, ResolutionStatus.TARGET_UNRESOLVED,
                                    "运行时浏览器证明缺少类型化交互规格。")
        if check.capability == "service.validate":
            name = self._first(candidates, "service.validate")
            service = self._service_arguments(check.observable, profile)
            if name and service:
                return self._result(name, {**common, **service}, check,
                                    "运行时 API 检查提供了可解析的方法、路径与状态可观测量。")
        if check.capability == "validation.structure":
            html = next((p for p in check_paths if p.endswith(".html")), None)
            name = self._first(candidates, "validation.static_web") if html else None
            if name and html:
                return self._result(name, {**common, "path": html, "expected_text": check.observable}, check,
                                    "结构性检查使用静态产物验证器。")
            command = self._structure_command(check, check_paths)
            name = self._first(candidates, "process.run")
            if name and command:
                return self._result(name, {**common, "command": command}, check,
                                    "结构性检查具有精确的本地文件断言。")
        test_tool = self._first(candidates, "test.run")
        if test_tool:
            selected = self.test_target_resolver.resolve(check_paths, revision=revision)
            wants_regression = check.strength >= EvidenceStrength.REGRESSION or check.purpose.value == "regression"
            if selected.selected_path and (wants_regression or selected.acceptance_supported):
                return self._result(test_tool, {**common, "path": selected.selected_path}, check, selected.reason)
        command_tool = self._first(candidates, "process.run")
        if command_tool and check.target:
            return self._result(command_tool, {**common, "command": check.target}, check,
                                "绑定的证明目标是可执行命令。")
        expected = check.capability
        return self._unresolved(check, ResolutionStatus.CAPABILITY_MISSING if expected not in candidates or not candidates[expected]
                                else ResolutionStatus.TARGET_UNRESOLVED,
                                f"所需能力 {expected} 不存在安全的验证器解析结果。")

    @staticmethod
    def _tools_by_capability(registry):
        capabilities = ("process.run", "test.run", "validation.static_web",
                        "validation.browser", "service.validate", "validation.semantic")
        finder = getattr(registry, "tool_names_for_capability", None)
        if callable(finder):
            return {capability: finder(capability) for capability in capabilities}
        return {
            capability: tuple(name for name in getattr(registry, "_tools", {})
                              if capability in registry.capabilities_for(name))
            for capability in capabilities
        }

    @staticmethod
    def _first(candidates, capability):
        return next(iter(candidates.get(capability, ())), None)

    @staticmethod
    def _result(tool_name, arguments, check, reason):
        return (ValidatorResolution(check_id=check.id, tool_name=tool_name, arguments=arguments, reason=reason)
                if tool_name else None)

    def _resolve_capability(self, candidates, capability, check, common, arguments, reason):
        name = self._first(candidates, capability)
        if not name:
            return self._unresolved(check, ResolutionStatus.CAPABILITY_MISSING,
                                    f"所需能力 {capability} 不可用。")
        return self._result(name, {**common, **arguments}, check, reason)

    @staticmethod
    def _unresolved(check, status, reason):
        return ValidatorResolution(check_id=check.id, reason=reason, status=status)

    @staticmethod
    def _paths_from_observable(observable):
        return tuple(re.findall(r"[\w./-]+\.(?:py|html|md|txt|yaml|yml|json)\b", observable or ""))

    @staticmethod
    def _structure_command(check, paths):
        path = next(iter(paths), None)
        if not path:
            return ""
        # File existence is a deterministic structural contract. Content semantics
        # deliberately stay unresolved unless an exact observable is supplied.
        if "exists" in check.observable.casefold():
            return f"test -f {path!r}"
        return ""

    @staticmethod
    def _service_arguments(observable, profile):
        match = re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s,→]+).*?\b([1-5]\d{2})\b", observable, re.I)
        commands = dict(getattr(profile, "commands", ()) or ())
        argv = commands.get("start") or commands.get("dev")
        if not match or not argv or "{port}" not in argv:
            return None
        try:
            executable = shlex.split(argv)
        except ValueError:
            return None
        if not executable:
            return None
        method, path, status = match.groups()
        if not 100 <= int(status) <= 599:
            return None
        return {
            "argv": executable,
            # Zero is the validator's documented ephemeral-port sentinel.  It
            # keeps planning deterministic and avoids the resolver reserving a
            # port that can race before the validator starts.
            "port": 0,
            "path": path.rstrip(".,;") or "/",
            "method": method.upper(),
            "expected_status": int(status),
            "expected_text": "",
        }

    @staticmethod
    def _service_arguments_from_spec(spec, profile):
        commands = dict(getattr(profile, "commands", ()) or ())
        argv = commands.get("start") or commands.get("dev")
        if not argv or "{port}" not in argv:
            return None
        try:
            executable = shlex.split(argv)
        except ValueError:
            return None
        arguments = {"argv": executable, "port": 0, "path": spec.path, "method": spec.method,
                     "expected_status": spec.expected_status, "expected_text": spec.expected_text}
        if spec.json_body is not None:
            arguments["json_body"] = spec.json_body
        return arguments
