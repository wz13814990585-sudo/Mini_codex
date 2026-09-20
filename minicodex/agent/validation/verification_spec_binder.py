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
        if check.spec is not None and (check.spec_source in {"explicit", "requirement"} or check.spec_bound_revision == session.revision):
            return BindingResult(check, "已绑定")
        impact_tests = getattr(impact, "tests", ()) if impact else ()
        paths = tuple(dict.fromkeys((*getattr(requirement, "paths", ()), *getattr(session, "recent_paths", ()),
                                     *impact_tests)))
        if check.capability == "validation.browser":
            return self._bind_browser(check, requirement, session, paths)
        if check.capability == "service.validate":
            return self._bind_http(check, requirement, session, paths)
        if check.capability == "validation.behavior":
            selected = self._rank_test_target(requirement, session, impact)
            if selected:
                return BindingResult(replace(check, spec=TestVerificationSpec(
                    source_path=(getattr(requirement, "paths", ()) or ("",))[0], test_target=selected),
                    spec_source="test_index", spec_bound_revision=session.revision),
                    f"已绑定排序后的聚焦已有测试 {selected}")
        return BindingResult(check, "没有可靠的仓库派生规格")

    def _rank_test_target(self, requirement, session, impact):
        """Select one focused test only when the deterministic winner is clear."""
        candidates = tuple(dict.fromkeys(getattr(impact, "tests", ()) if impact else ()))
        candidates = tuple(path for path in candidates if self._is_test_path(path) and path in set(session.paths))
        if not candidates:
            return ""
        source_paths = tuple(getattr(requirement, "paths", ()) or ())
        words = set(re.findall(r"[a-z][a-z0-9_]+", f"{requirement.description} {requirement.observable}".casefold()))
        scored = []
        for candidate in candidates:
            name_words = set(re.findall(r"[a-z][a-z0-9_]+", candidate.casefold()))
            score = len(words & name_words) * 3
            source_stems = {Path(path).stem.casefold() for path in source_paths}
            score += sum(stem in candidate.casefold() for stem in source_stems) * 5
            score += 2 if candidate in getattr(session, "recent_paths", ()) else 0
            score -= 3 if candidate.rstrip("/").endswith(("tests", "test")) else 0
            scored.append((score, candidate))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if len(scored) == 1 or scored[0][0] > scored[1][0]:
            return scored[0][1]
        return ""

    @staticmethod
    def _is_test_path(path):
        candidate = Path(path.split("::", 1)[0])
        return candidate.name.startswith("test_") or candidate.name.endswith("_test.py") or "tests" in candidate.parts

    def _bind_browser(self, check, requirement, session, paths):
        html_candidates = tuple(dict.fromkeys(path for path in (*paths, *session.recent_paths, *session.paths) if path.endswith(".html")))
        html = next((path for path in html_candidates if path in paths or path in session.recent_paths), "")
        if not html:
            return BindingResult(check, "未发现 HTML 目标")
        content = self._read(session, html)
        state_candidates = re.findall(r"(?:id|data-testid|aria-label)=[\"']([^\"']+)[\"']", content, re.I)
        terms = set(re.findall(r"[a-z][a-z0-9_-]+", f"{requirement.description} {requirement.observable}".casefold()))
        state_candidates.sort(key=lambda value: (-(len(set(re.findall(r"[a-z][a-z0-9_-]+", value.casefold())) & terms) * 3
                                                   + (2 if re.search(r"state|status|output|result|message|score", value, re.I) else 0)), value))
        state = state_candidates[0] if state_candidates else ""
        key = re.search(r"Arrow(?:Left|Right|Up|Down)", requirement.observable, re.I)
        click = re.search(r"(?:click|press)\s+(?:the\s+)?[#.]?([\w-]+)", requirement.observable, re.I)
        expected = (re.search(r"(?:to|text to|state to)\s+[\"']?([\w-]+)", requirement.observable, re.I)
                    or re.search(r"\b(?:moves?|changes?)\b.*?\b(left|right|up|down|moved)\b", requirement.observable, re.I))
        if not (state and (key or click) and expected):
            return BindingResult(check, "未发现浏览器操作后选择器或期望状态")
        action, value, selector = ("keypress", key.group(0), f"#{state}") if key else ("click", "", f"#{click.group(1)}")
        return BindingResult(replace(check, spec=BrowserVerificationSpec(
            html, selector, action, value, expected.group(1), "text", f"#{state}", expected.group(1)),
            spec_source="repository", spec_bound_revision=session.revision),
            "已根据检查到的 DOM 绑定浏览器状态转换")

    def _bind_http(self, check, requirement, session, paths):
        candidates = []
        terms = set(re.findall(r"[a-z][a-z0-9_/-]+", f"{requirement.description} {requirement.observable}".casefold()))
        requested_status = re.search(r"\b([1-5]\d{2})\b", requirement.observable)
        for path in dict.fromkeys((*paths, *session.paths)):
            if not path.endswith(".py"):
                continue
            content = self._read(session, path)
            for route in re.finditer(r"@\w+(?:\.\w+)?\.(get|post|put|patch|delete)\(\s*[\"']([^\"']+)[\"'][^)]*\).*?(?:async\s+)?def\s+(\w+)", content, re.I | re.S):
                method, route_path, handler = route.groups()
                words = set(re.findall(r"[a-z][a-z0-9_/-]+", f"{route_path} {handler} {path}".casefold()))
                score = len(words & terms) * 3 + (2 if path in paths or path in session.recent_paths else 0)
                candidates.append((score, method.upper(), route_path, path, handler))
        if candidates and requested_status:
            candidates.sort(reverse=True)
            best = candidates[0]
            if best[0] > 0 and (len(candidates) == 1 or best[0] > candidates[1][0]):
                return BindingResult(replace(check, spec=HttpVerificationSpec(best[1], best[2], int(requested_status.group(1))),
                                             spec_source="repository", spec_bound_revision=session.revision),
                                     f"已从 {best[3]} 绑定排序后的 HTTP 路由 {best[1]} {best[2]}")
        return BindingResult(check, "未发现明确的路由与状态契约")

    @staticmethod
    def _read(session, path):
        try:
            return (Path(session.workspace) / path).read_text(encoding="utf-8")[:32_000]
        except (OSError, UnicodeError):
            return ""
