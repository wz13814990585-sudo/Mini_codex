"""Artifact-aware selection of one proportional acceptance validator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationSelection:
    tool_name: str
    path: str | None
    purpose: str
    reason: str


class ValidationSelector:
    """Recommend at most one validator; execution remains in the shared loop."""

    def select(
        self,
        *,
        target_paths: tuple[str, ...],
        registered_tools: set[str],
        runtime_behavior: bool = False,
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
        python_target = next((path for path in target_paths if path.lower().endswith(".py")), None)
        if "run_tests" in registered_tools:
            return ValidationSelection(
                "run_tests", python_target, "acceptance",
                "Python behavior should be demonstrated by a focused test.",
            )
        if "run_command" in registered_tools:
            return ValidationSelection(
                "run_command", None, "acceptance",
                "No dedicated artifact validator is available.",
            )
        return None
