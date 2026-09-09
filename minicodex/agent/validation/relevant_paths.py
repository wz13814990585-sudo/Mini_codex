"""Deterministic path set used to bound failure-fixing actions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...utils.paths import resolve_workspace_path


@dataclass(frozen=True)
class RelevantPathSet:
    paths: tuple[str, ...]
    reasons: dict[str, tuple[str, ...]]


class RelevantPathResolver:
    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()

    def resolve(self, agent) -> RelevantPathSet:
        reasons: dict[str, list[str]] = {}

        def add(value, reason: str) -> None:
            normalized = self._normalize(value)
            if normalized is None:
                return
            reasons.setdefault(normalized, [])
            if reason not in reasons[normalized]:
                reasons[normalized].append(reason)

        route = getattr(agent, "execution_route", None)
        for path in getattr(route, "target_paths", ()) or ():
            add(path, "requested target")

        awareness = getattr(agent, "git_awareness", None)
        if awareness is not None:
            try:
                for path in awareness.task_state().agent_touched_files:
                    add(path, "agent edit")
            except Exception:
                pass

        state = getattr(getattr(agent, "validation_pipeline", None), "state", None)
        evidence = getattr(state, "latest_evidence", None)
        if evidence is not None:
            add(getattr(evidence, "path", None), "validation target")
            details = getattr(evidence, "details", {}) or {}
            for path in details.get("failure_paths", ()):
                add(path, "validation failure")
            for key in ("manifest", "dependency_manifest", "requirements_path"):
                add(details.get(key), "dependency failure evidence")

        plan = getattr(agent, "active_plan", None)
        if plan is not None:
            for step in plan.all_steps():
                for criterion in getattr(step, "acceptance_criteria", ()) or ():
                    add(criterion.get("path"), "acceptance criterion")

        pending = getattr(getattr(agent, "edit_retry", None), "pending", None)
        if pending is not None:
            add(getattr(pending, "path", None), "stale edit target")

        for path in getattr(agent, "latest_symbol_recovery_paths", ()) or ():
            add(path, "symbol-search recovery")

        dependency = getattr(agent, "latest_dependency_resolution", None)
        if dependency is not None and getattr(dependency, "action", "") == "update_manifest_first":
            add(getattr(dependency, "preferred_manifest", None), "requested dependency update")

        if evidence is not None and details.get("failure_type") == "missing_dependency":
            for manifest in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg"):
                if (self.workspace / manifest).is_file():
                    add(manifest, "dependency failure evidence")

        return RelevantPathSet(
            paths=tuple(reasons),
            reasons={path: tuple(values) for path, values in reasons.items()},
        )

    def _normalize(self, value) -> str | None:
        text = str(value or "").strip().split("::", 1)[0]
        if not text or "\n" in text or "\r" in text:
            return None
        # Commands are evidence labels, not paths.
        if any(token in text for token in (" ", "&&", "||", ";")):
            return None
        try:
            resolved = resolve_workspace_path(self.workspace, text)
            return resolved.relative_to(self.workspace).as_posix()
        except (ValueError, OSError):
            return None
