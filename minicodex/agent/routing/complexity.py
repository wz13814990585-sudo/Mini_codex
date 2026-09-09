"""Route execution complexity without deciding whether edits are authorized."""

from __future__ import annotations

from dataclasses import dataclass

from .execution_mode import ExecutionMode


@dataclass(frozen=True)
class ComplexityRoute:
    mode: ExecutionMode
    score: int
    reason: str
    signals: tuple[str, ...]


class ComplexityRouter:
    _SMALL_ACTIONS = (
        "add a button", "update css", "modify readme", "update readme",
        "hello world", "one existing python function", "single function",
        "standalone html", "simple python bug", "small python bug",
        "添加按钮", "更新 css", "修改 readme", "单个函数", "独立 html", "简单 python 错误",
    )

    def route(self, user_request: str, target_paths: tuple[str, ...]) -> ComplexityRoute:
        lowered = str(user_request or "").casefold()
        signals: list[str] = []
        score = 0

        def add(markers: tuple[str, ...], points: int, label: str) -> None:
            nonlocal score
            for marker in markers:
                if marker in lowered:
                    score += points
                    signals.append(f"score:{points:+d}:{label}:{marker}")

        add(("state machine", "状态机"), 3, "state-machine")
        add(
            ("concurrency", "并发", "cancellation", "取消", "security", "安全", "multi-agent", "多智能体"),
            3,
            "high-risk",
        )
        add(("control plane", "控制平面", "migration", "迁移"), 2, "cross-cutting")
        add(
            ("validation architecture", "rollback architecture", "memory architecture", "completion routing"),
            2,
            "architecture-subsystem",
        )
        if ("async runtime" in lowered or "异步运行时" in lowered) and (
            "architecture" in lowered or "架构" in lowered
        ):
            score += 4
            signals.append("score:+4:async-runtime-architecture")
        if any(word in lowered for word in ("refactor", "redesign", "重构", "重新设计")) and any(
            word in lowered for word in ("architecture", "架构", "orchestration", "编排", "runtime", "运行时")
        ):
            score += 2
            signals.append("score:+2:architectural-change")

        standard_hits = tuple(
            marker
            for marker in (
                "fastapi endpoint", "several files", "three files", "3 files",
                "medium bug", "regression bug", "多个文件", "中等错误",
            )
            if marker in lowered
        )
        if len(target_paths) >= 3 or standard_hits:
            score += 3
            signals.append("score:+3:coordinated-multi-file")

        fast_scope = any(
            path.casefold().startswith(("try_code/", "examples/", "docs/"))
            or path.casefold().startswith("readme")
            for path in target_paths
        )
        html_game = (
            ("html" in lowered or any(path.lower().endswith(".html") for path in target_paths))
            and any(word in lowered for word in ("game", "tetris", "snake", "游戏", "俄罗斯方块", "贪吃蛇"))
        )
        small_game = any(word in lowered for word in ("game", "tetris", "snake", "游戏", "俄罗斯方块", "贪吃蛇")) and any(
            marker in lowered for marker in ("try_code", "standalone", "single-file", "单文件")
        )
        small_action = any(marker in lowered for marker in self._SMALL_ACTIONS)
        if fast_scope:
            score -= 3
            signals.append("score:-3:bounded-artifact")
        if html_game or small_game or small_action:
            score -= 2
            signals.append("score:-2:small-local-action")

        if score >= 4:
            mode = ExecutionMode.COMPLEX
            reason = f"Complexity score {score}: cross-cutting or high-risk work."
        elif score >= 1:
            mode = ExecutionMode.STANDARD
            reason = f"Complexity score {score}: coordinated bounded work."
        elif score < 0:
            mode = ExecutionMode.FAST
            reason = f"Complexity score {score}: clearly local and bounded work."
        else:
            mode = ExecutionMode.STANDARD
            reason = "No decisive fast-path or complex-task score was found."
            signals.append("uncertain-medium-scope")
        return ComplexityRoute(mode, score, reason, tuple(signals))
