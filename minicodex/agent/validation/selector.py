"""Artifact-aware selection of one proportional acceptance validator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .test_target_resolver import TestTargetResolver


@dataclass(frozen=True)
class ValidationSelection:
    tool_name: str
    path: str | None
    purpose: str
    reason: str


class ValidationSelector:
    """Recommend at most one validator; execution remains in the shared loop."""

    def __init__(self, workspace: str | Path = ".") -> None:
        self.test_target_resolver = TestTargetResolver(workspace)

    def select(
        self,
        *,
        target_paths: tuple[str, ...],
        registered_tools: set[str],
        runtime_behavior: bool = False,
        revision: object = 0,
        desired_purpose: str = "acceptance",
    ) -> ValidationSelection | None:
        html = next((path for path in target_paths if path.lower().endswith(".html")), None)
        if html and runtime_behavior and "validate_browser_app" in registered_tools:
            return ValidationSelection(
                "validate_browser_app", html, "acceptance",
                "Runtime browser behavior was requested and a browser validator is registered.",
            )
        if html and "validate_static_web" in registered_tools:
            return ValidationSelection(
                "validate_static_web", html, "acceptance",
                "A bounded static web artifact has a dedicated validator.",
            )
        python_targets = tuple(path for path in target_paths if path.lower().endswith(".py"))
        regression_fallback = None
        if "run_tests" in registered_tools:
            resolution = self.test_target_resolver.resolve(python_targets, revision=revision)
            if resolution.acceptance_supported:
                return ValidationSelection(
                    "run_tests",
                    resolution.selected_path,
                    "regression" if desired_purpose == "regression" else "acceptance",
                    resolution.reason,
                )
            if resolution.selected_path:
                regression_fallback = ValidationSelection(
                    "run_tests", resolution.selected_path, "regression", resolution.reason
                )
                if desired_purpose == "regression":
                    return regression_fallback
        if "run_command" in registered_tools:
            return ValidationSelection(
                "run_command", None, "acceptance",
                "No focused pytest target exists; use a specific behavior command.",
            )
        return regression_fallback
