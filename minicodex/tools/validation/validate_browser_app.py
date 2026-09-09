"""Optional Playwright-backed runtime validation for local web artifacts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from ..base import BaseTool
from ...utils.paths import resolve_workspace_path
from ..results import ToolResult


class ValidateBrowserAppTool(BaseTool):
    name = "validate_browser_app"
    capabilities = frozenset({"validation.browser"})
    description = (
        "Run bounded Playwright checks against one local HTML file: page load, "
        "console errors, selector/text assertions, click, keypress, and resulting text."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative HTML path."},
            "selector": {"type": "string", "description": "Selector that must exist."},
            "expected_text": {"type": "string", "description": "Text expected after actions."},
            "click_selector": {"type": "string", "description": "Optional selector to click."},
            "keypress": {"type": "string", "description": "Optional Playwright key name."},
            "keypress_selector": {"type": "string", "description": "Optional keypress target."},
        },
        "required": ["path"],
    }

    def __init__(self, workspace: str | Path = ".", timeout_ms: int = 5000) -> None:
        self.workspace = Path(workspace).resolve()
        self.timeout_ms = max(250, int(timeout_ms))

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("playwright") is not None

    def execute(
        self,
        path: str,
        selector: str = "",
        expected_text: str = "",
        click_selector: str = "",
        keypress: str = "",
        keypress_selector: str = "",
    ) -> ToolResult:
        target = resolve_workspace_path(self.workspace, path)
        if not target.is_file():
            return self._result(path, "failed", [f"HTML file not found: {path}"])
        if not self.available():
            return ToolResult(
                success=False,
                summary="Browser validation is unavailable; Playwright is not installed.",
                data={
                    "path": path,
                    "outcome": "inconclusive",
                    "failure_type": "missing_dependency",
                    "fallback": "validate_static_web",
                },
                error="Optional dependency 'playwright' is unavailable.",
            )

        from playwright.sync_api import sync_playwright

        errors: list[str] = []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_default_timeout(self.timeout_ms)
                page.on(
                    "console",
                    lambda message: errors.append(f"console: {message.text}")
                    if message.type == "error"
                    else None,
                )
                page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
                page.goto(target.as_uri(), wait_until="load")
                if selector and page.locator(selector).count() == 0:
                    errors.append(f"selector not found: {selector}")
                if click_selector:
                    page.locator(click_selector).click()
                if keypress:
                    if keypress_selector:
                        page.locator(keypress_selector).press(keypress)
                    else:
                        page.keyboard.press(keypress)
                if expected_text:
                    actual = (
                        page.locator(selector).first.inner_text()
                        if selector and page.locator(selector).count()
                        else page.locator("body").inner_text()
                    )
                    if expected_text not in actual:
                        errors.append(f"expected text not found: {expected_text}")
                browser.close()
        except Exception as error:
            return ToolResult(
                success=False,
                summary="Browser validation could not execute.",
                data={
                    "path": path,
                    "outcome": "inconclusive",
                    "failure_type": "sandbox_start_failed",
                    "fallback": "validate_static_web",
                },
                error=f"{type(error).__name__}: {error}",
            )
        return self._result(path, "failed" if errors else "passed", errors)

    @staticmethod
    def _result(path: str, outcome: str, errors: list[str]) -> ToolResult:
        return ToolResult(
            success=True,
            summary=(
                "Browser acceptance validation passed."
                if outcome == "passed"
                else f"Browser acceptance validation found {len(errors)} error(s)."
            ),
            data={"path": path, "outcome": outcome, "errors": errors},
        )
