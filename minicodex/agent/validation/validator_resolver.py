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
                                HttpVerificationSpec, SemanticVerificationSpec)


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
        if isinstance(spec, CommandVerificationSpec):
            return self._resolve_capability(candidates, "process.run", check, common,
                                            {"command": spec.command}, "The spec binds a configured command.")
        if isinstance(spec, HttpVerificationSpec):
            service = self._service_arguments_from_spec(spec, profile)
            if service is None:
                return self._unresolved(check, ResolutionStatus.TARGET_UNRESOLVED,
                                        "HTTP proof needs a safe profile start/dev command containing {port}.")
            return self._resolve_capability(candidates, "service.validate", check, common, service,
                                            "The typed HTTP contract supplies method, path, and expected status.")
        if isinstance(spec, BrowserVerificationSpec):
            if not spec.action or not spec.selector:
                return self._unresolved(check, ResolutionStatus.TARGET_UNRESOLVED,
                                        "Interactive browser proof needs an action, selector, and post-action assertion.")
            action_args = ({"keypress": spec.value, "keypress_selector": spec.selector}
                           if spec.action == "keypress" else {"click_selector": spec.selector})
            return self._resolve_capability(candidates, "validation.browser", check, common,
                                            {"path": spec.path, "selector": spec.selector,
                                             "expected_text": spec.expected_text, **action_args},
                                            "The typed browser interaction defines the exact assertion.")
        if isinstance(spec, FileVerificationSpec):
            name = self._first(candidates, "validation.static_web") if spec.path.endswith(".html") else None
            if name:
                return self._result(name, {**common, "path": spec.path, "expected_text": spec.contains}, check,
                                    "The file spec maps to static validation.")
        if isinstance(spec, SemanticVerificationSpec):
            return self._resolve_capability(candidates, "validation.semantic", check, common,
                                            {"path": spec.path, "claim": spec.claim},
                                            "The semantic claim requires the semantic validator.")
        if check.capability == "process.run" and check.target:
            return self._resolve_capability(candidates, "process.run", check, common,
                                            {"command": check.target}, "The plan supplies its exact configured command.")
        if check.capability == "validation.browser":
            if not self._first(candidates, "validation.browser"):
                return self._unresolved(check, ResolutionStatus.CAPABILITY_MISSING,
                                        "Required capability validation.browser is unavailable.")
            return self._unresolved(check, ResolutionStatus.TARGET_UNRESOLVED,
                                    "Runtime browser proof has no typed interaction specification.")
        if check.capability == "service.validate":
            name = self._first(candidates, "service.validate")
            service = self._service_arguments(check.observable, profile)
            if name and service:
                return self._result(name, {**common, **service}, check,
                                    "The runtime API check supplied a parseable method, path, and status observable.")
        if check.capability == "validation.structure":
            html = next((p for p in check_paths if p.endswith(".html")), None)
            name = self._first(candidates, "validation.static_web") if html else None
            if name and html:
                return self._result(name, {**common, "path": html, "expected_text": check.observable}, check,
                                    "The structural check uses the static artifact validator.")
            command = self._structure_command(check, check_paths)
            name = self._first(candidates, "process.run")
            if name and command:
                return self._result(name, {**common, "command": command}, check,
                                    "The structural check has an exact local file assertion.")
        test_tool = self._first(candidates, "test.run")
        if test_tool:
            selected = self.test_target_resolver.resolve(check_paths, revision=revision)
            wants_regression = check.strength >= EvidenceStrength.REGRESSION or check.purpose.value == "regression"
            if selected.selected_path and (wants_regression or selected.acceptance_supported):
                return self._result(test_tool, {**common, "path": selected.selected_path}, check, selected.reason)
        command_tool = self._first(candidates, "process.run")
        if command_tool and check.target:
            return self._result(command_tool, {**common, "command": check.target}, check,
                                "The bound proof target is an executable command.")
        expected = check.capability
        return self._unresolved(check, ResolutionStatus.CAPABILITY_MISSING if expected not in candidates or not candidates[expected]
                                else ResolutionStatus.TARGET_UNRESOLVED,
                                f"No safe validator resolution exists for required capability {expected}.")

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
                                    f"Required capability {capability} is unavailable.")
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
        match = re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s,→]+).*?\b(\d{3})\b", observable, re.I)
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
        return {"argv": executable, "port": 0, "path": spec.path, "method": spec.method,
                "expected_status": spec.expected_status, "expected_text": spec.expected_text,
                "json_body": spec.json_body}
