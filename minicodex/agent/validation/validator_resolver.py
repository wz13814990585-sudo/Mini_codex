"""Resolve one missing proof obligation to a registered validator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex

from .plan import EvidenceStrength, ValidationCheck
from .test_target_resolver import TestTargetResolver


@dataclass(frozen=True)
class ValidatorResolution:
    tool_name: str
    arguments: dict
    check_id: str
    reason: str


class ValidatorResolver:
    """Capability-first, bounded resolution; it never invents a different check."""

    def __init__(self, workspace: str | Path = ".", *, test_index=None) -> None:
        self.test_target_resolver = TestTargetResolver(workspace, test_index=test_index)

    def resolve(self, check: ValidationCheck, *, registry, profile=None, paths=(), revision=0):
        candidates = self._tools_by_capability(registry)
        check_paths = tuple(dict.fromkeys((*paths, *self._paths_from_observable(check.observable))))
        common = {"purpose": check.purpose.value, "validation_check": check.id}
        if check.capability == "process.run" and check.target:
            name = self._first(candidates, "process.run")
            return self._result(name, {**common, "command": check.target}, check, "The plan supplies its exact configured command.")
        if check.capability == "validation.browser":
            name = self._first(candidates, "validation.browser")
            html = next((p for p in check_paths if p.endswith(".html")), None)
            if name and html:
                return self._result(name, {**common, "path": html, "expected_text": check.observable}, check,
                                    "The runtime check targets the requested HTML artifact and observable.")
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
        return None

    @staticmethod
    def _tools_by_capability(registry):
        capabilities = ("process.run", "test.run", "validation.static_web",
                        "validation.browser", "service.validate")
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
        return ValidatorResolution(tool_name, arguments, check.id, reason) if tool_name else None

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
