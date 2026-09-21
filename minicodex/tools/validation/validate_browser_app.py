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
        "对单个本地 HTML 文件执行有界的 Playwright 检查：页面加载、"
        "控制台错误、选择器/文本断言、点击、按键，以及操作后的文本。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "工作区相对的 HTML 路径。"},
            "selector": {"type": "string", "description": "必须存在的选择器。"},
            "expected_text": {"type": "string", "description": "操作后期望出现的文本。"},
            "click_selector": {"type": "string", "description": "可选：要点击的选择器。"},
            "keypress": {"type": "string", "description": "可选：Playwright 按键名。"},
            "keypress_selector": {"type": "string", "description": "可选：按键目标选择器。"},
            "assertion_kind": {"type": "string", "enum": ["text", "visible", "value", "attribute", "class", "style"], "description": "操作后的断言类型。"},
            "expected_value": {"type": "string", "description": "操作后断言的期望值。"},
            "non_target_action_type": {"type": "string", "enum": ["click", "keypress"]},
            "non_target_action_selector": {"type": "string"},
            "non_target_action_value": {"type": "string"},
            "non_target_assertion_selector": {"type": "string"},
            "non_target_expected_value": {"type": "string"},
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
        assertion_kind: str = "",
        expected_value: str = "",
        non_target_action_type: str = "",
        non_target_action_selector: str = "",
        non_target_action_value: str = "",
        non_target_assertion_selector: str = "",
        non_target_expected_value: str = "",
    ) -> ToolResult:
        target = resolve_workspace_path(self.workspace, path)
        if not target.is_file():
            return self._result(path, "failed", [f"未找到 HTML 文件：{path}"])
        if not self.available():
            return ToolResult(
                success=False,
                summary="浏览器验证不可用；未安装 Playwright。",
                data={
                    "path": path,
                    "outcome": "inconclusive",
                    "failure_type": "missing_dependency",
                    "fallback": "validate_static_web",
                },
                error="可选依赖 'playwright' 不可用。",
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
                if non_target_action_type:
                    self._perform_action(
                        page, non_target_action_type, non_target_action_selector,
                        non_target_action_value,
                    )
                    actual = page.locator(non_target_assertion_selector).first.inner_text()
                    if actual != non_target_expected_value:
                        errors.append(
                            "非目标操作改变了状态："
                            f"{non_target_assertion_selector}={actual!r}，"
                            f"期望 {non_target_expected_value!r}"
                        )
                if selector and page.locator(selector).count() == 0:
                    errors.append(f"未找到选择器：{selector}")
                if click_selector:
                    page.locator(click_selector).click()
                if keypress:
                    if keypress_selector:
                        page.locator(keypress_selector).press(keypress)
                    else:
                        page.keyboard.press(keypress)
                assertion_kind = assertion_kind or ("text" if expected_text else "")
                expected_value = expected_value or expected_text
                if assertion_kind == "text":
                    actual = (
                        page.locator(selector).first.inner_text()
                        if selector and page.locator(selector).count()
                        else page.locator("body").inner_text()
                    )
                    if actual != expected_value:
                        errors.append(f"文本不等于期望值：{expected_value}")
                elif assertion_kind == "visible" and not page.locator(selector).first.is_visible():
                    errors.append(f"选择器不可见：{selector}")
                elif assertion_kind == "value" and page.locator(selector).first.input_value() != expected_value:
                    errors.append(f"未找到期望值：{expected_value}")
                elif assertion_kind == "class" and expected_value not in (page.locator(selector).first.get_attribute("class") or "").split():
                    errors.append(f"未找到期望 class：{expected_value}")
                elif assertion_kind == "attribute":
                    name, _, value = expected_value.partition("=")
                    if not name or page.locator(selector).first.get_attribute(name) != value:
                        errors.append(f"未找到期望属性：{expected_value}")
                elif assertion_kind == "style" and expected_value not in (page.locator(selector).first.get_attribute("style") or ""):
                    errors.append(f"未找到期望 style：{expected_value}")
                browser.close()
        except Exception as error:
            return ToolResult(
                success=False,
                summary="无法执行浏览器验证。",
                data={
                    "path": path,
                    "outcome": "inconclusive",
                    "failure_type": "sandbox_start_failed",
                    "fallback": "validate_static_web",
                },
                error=f"{type(error).__name__}: {error}",
            )
        result = self._result(path, "failed" if errors else "passed", errors)
        result.data["evidence_strength"] = 5 if assertion_kind and expected_value and (click_selector or keypress) else 0
        return result

    @staticmethod
    def _perform_action(page, action_type: str, selector: str, value: str) -> None:
        if action_type == "click":
            page.locator(selector).click()
        elif action_type == "keypress":
            if selector:
                page.locator(selector).press(value)
            else:
                page.keyboard.press(value)
        else:
            raise ValueError(f"不支持的浏览器 action：{action_type}")

    @staticmethod
    def _result(path: str, outcome: str, errors: list[str]) -> ToolResult:
        return ToolResult(
            success=True,
            summary=(
                "浏览器验收验证通过。"
                if outcome == "passed"
                else f"浏览器验收验证发现 {len(errors)} 个错误。"
            ),
            data={"path": path, "outcome": outcome, "errors": errors},
        )
