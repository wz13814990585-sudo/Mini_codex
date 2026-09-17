"""Late-bind abstract validation checks from current workspace facts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re

from .verification_spec import BrowserVerificationSpec, HttpVerificationSpec, TestVerificationSpec


@dataclass(frozen=True)
class BindingResult:
    check: object
    reason: str = ""

    @property
    def bound(self):
        return self.check.spec is not None


class VerificationSpecBinder:
    """Uses inspected repository facts; it never fabricates an assertion."""

    def bind(self, check, requirement, *, session, impact=None):
        if check.spec is not None:
            return BindingResult(check, "already bound")
        impact_tests = getattr(impact, "tests", ()) if impact else ()
        paths = tuple(dict.fromkeys((*getattr(requirement, "paths", ()), *getattr(session, "recent_paths", ()),
                                     *impact_tests)))
        if check.capability == "validation.browser":
            return self._bind_browser(check, requirement, session, paths)
        if check.capability == "service.validate":
            return self._bind_http(check, requirement, session, paths)
        if check.capability == "validation.behavior":
            tests = tuple(getattr(impact, "tests", ()) if impact else ())
            if tests:
                return BindingResult(replace(check, spec=TestVerificationSpec(
                    source_path=(getattr(requirement, "paths", ()) or ("",))[0], test_target=tests[0])),
                    "bound focused existing test")
        return BindingResult(check, "no reliable repository-derived spec")

    def _bind_browser(self, check, requirement, session, paths):
        html = next((path for path in (*paths, *session.paths) if path.endswith(".html")), "")
        if not html:
            return BindingResult(check, "no HTML target discovered")
        content = self._read(session, html)
        state = re.search(r"id=[\"']([\w-]*(?:state|status|score)[\w-]*)[\"']", content, re.I)
        key = re.search(r"Arrow(?:Left|Right|Up|Down)", requirement.observable, re.I)
        expected = (re.search(r"(?:to|text to|state to)\s+[\"']?([\w-]+)", requirement.observable, re.I)
                    or re.search(r"\b(?:moves?|changes?)\b.*?\b(left|right|up|down|moved)\b", requirement.observable, re.I))
        if not (state and key and expected):
            return BindingResult(check, "browser post-action selector or expected state was not discovered")
        return BindingResult(replace(check, spec=BrowserVerificationSpec(
            html, f"#{state.group(1)}", "keypress", key.group(0), expected.group(1))),
            "bound browser state transition from inspected DOM")

    def _bind_http(self, check, requirement, session, paths):
        for path in (*paths, *session.paths):
            if not path.endswith(".py"):
                continue
            content = self._read(session, path)
            route = re.search(r"@\w+\.(get|post|put|patch|delete)\(\s*[\"']([^\"']+)", content, re.I)
            status = re.search(r"\b(401|400|403|404)\b", requirement.observable)
            if route and status:
                return BindingResult(replace(check, spec=HttpVerificationSpec(route.group(1).upper(), route.group(2), int(status.group(1)))),
                                     "bound HTTP route from inspected source")
        return BindingResult(check, "no route and status contract discovered")

    @staticmethod
    def _read(session, path):
        try:
            return (Path(session.workspace) / path).read_text(encoding="utf-8")[:32_000]
        except (OSError, UnicodeError):
            return ""
