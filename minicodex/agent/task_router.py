"""Deterministic task routing; no LLM call is involved."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .execution_mode import ExecutionMode


@dataclass(frozen=True)
class TaskRoute:
    mode: ExecutionMode
    reason: str
    signals: tuple[str, ...] = ()
    target_paths: tuple[str, ...] = ()


class TaskRouter:
    _PATH = re.compile(
        r"(?<![\w.-])([\w.-]+(?:[/\\][\w.-]+)+|README(?:\.md)?)",
        re.IGNORECASE,
    )
    _COMPLEX = (
        "architecture",
        "control plane",
        "harness",
        "migration",
        "concurrency",
        "async runtime",
        "cancellation",
        "security",
        "multi-module",
        "framework-level",
        "架构",
        "控制平面",
        "迁移",
        "并发",
        "异步运行时",
        "安全",
        "多模块",
    )
    _SMALL_ACTIONS = (
        "add a button",
        "update css",
        "modify readme",
        "update readme",
        "hello world",
        "one existing python function",
        "single function",
        "standalone html",
        "添加按钮",
        "更新 css",
        "修改 readme",
        "单个函数",
        "独立 html",
    )

    def route(self, user_request: str, repo_state=None) -> TaskRoute:
        text = str(user_request or "").strip()
        lowered = text.casefold()
        targets = tuple(dict.fromkeys(self._extract_paths(text)))
        signals: list[str] = []

        complex_hits = [item for item in self._COMPLEX if item in lowered]
        if complex_hits:
            signals.extend(f"complex:{item}" for item in complex_hits)
            return TaskRoute(
                mode=ExecutionMode.COMPLEX,
                reason="Request contains cross-cutting or high-risk architecture signals.",
                signals=tuple(signals),
                target_paths=targets,
            )

        fast_scope = any(
            path.casefold().startswith(("try_code/", "examples/", "docs/"))
            or path.casefold().startswith("readme")
            for path in targets
        )
        html_game = (
            ("html" in lowered or any(path.lower().endswith(".html") for path in targets))
            and any(word in lowered for word in ("game", "tetris", "snake", "游戏", "俄罗斯方块", "贪吃蛇"))
        )
        small_game = (
            any(
                word in lowered
                for word in ("game", "tetris", "snake", "游戏", "俄罗斯方块", "贪吃蛇")
            )
            and any(
                marker in lowered
                for marker in ("try_code", "standalone", "single-file", "单文件")
            )
        )
        one_explicit_target = len(targets) == 1
        small_action = any(item in lowered for item in self._SMALL_ACTIONS)

        if (
            fast_scope
            or html_game
            or small_game
            or small_action
            or one_explicit_target
        ):
            if fast_scope:
                signals.append("small-scope-path")
            if html_game:
                signals.append("standalone-html-game")
            if small_game:
                signals.append("small-game-scope")
            if one_explicit_target:
                signals.append("single-explicit-target")
            if small_action:
                signals.append("small-local-action")
            return TaskRoute(
                mode=ExecutionMode.FAST,
                reason="Request is clearly local and bounded to a small artifact.",
                signals=tuple(signals),
                target_paths=targets,
            )

        return TaskRoute(
            mode=ExecutionMode.STANDARD,
            reason="No decisive fast-path or complex-task signal was found.",
            signals=("uncertain-medium-scope",),
            target_paths=targets,
        )

    @classmethod
    def _extract_paths(cls, text: str) -> list[str]:
        return [
            match.group(1).replace("\\", "/").rstrip(".,:;)")
            for match in cls._PATH.finditer(text)
        ]
