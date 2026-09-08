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
    requires_coding_action: bool = True


@dataclass(frozen=True)
class RoutingRule:
    name: str
    mode: ExecutionMode
    description: str


class TaskRouter:
    _PATH = re.compile(
        r"(?<![\w.-])([\w.-]+(?:[/\\][\w.-]+)+|"
        r"[\w.-]+\.(?:py|html|css|js|md|toml|json|ya?ml)|README(?:\.md)?)",
        re.IGNORECASE,
    )
    _COMPLEX = (
        "architecture",
        "control plane",
        "harness",
        "orchestration",
        "state machine",
        "runtime",
        "migration",
        "concurrency",
        "async runtime",
        "cancellation",
        "security",
        "rollback architecture",
        "validation architecture",
        "memory architecture",
        "multi-agent",
        "multi-module",
        "framework-level",
        "架构",
        "控制平面",
        "编排",
        "状态机",
        "运行时",
        "迁移",
        "并发",
        "异步运行时",
        "安全",
        "多模块",
        "多智能体",
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
        "simple python bug",
        "small python bug",
        "简单 python 错误",
    )
    RULE_TABLE = (
        RoutingRule(
            "architecture_or_high_risk",
            ExecutionMode.COMPLEX,
            "Cross-cutting runtime, architecture, security, or concurrency work.",
        ),
        RoutingRule(
            "bounded_local_artifact",
            ExecutionMode.FAST,
            "One clearly named small artifact or function.",
        ),
        RoutingRule(
            "medium_or_multi_file",
            ExecutionMode.STANDARD,
            "Feature or bug work spanning several files and focused tests.",
        ),
        RoutingRule(
            "uncertain_default",
            ExecutionMode.STANDARD,
            "Ambiguous work receives planning and focused regression by default.",
        ),
    )
    _CODING_ACTION = re.compile(
        r"\b(create|add|update|fix|refactor|redesign|implement|build|modify|"
        r"change|remove|delete|write|improve)\b|"
        r"(创建|新增|添加|更新|修复|重构|重新设计|实现|构建|修改|改动|删除|编写|优化|做一个)",
        re.IGNORECASE,
    )

    def route(self, user_request: str, repo_state=None) -> TaskRoute:
        text = str(user_request or "").strip()
        lowered = text.casefold()
        targets = tuple(dict.fromkeys(self._extract_paths(text)))
        signals: list[str] = []
        requires_coding_action = bool(self._CODING_ACTION.search(text))

        complex_hits = [item for item in self._COMPLEX if item in lowered]
        if complex_hits:
            signals.extend(f"complex:{item}" for item in complex_hits)
            return TaskRoute(
                mode=ExecutionMode.COMPLEX,
                reason="Request contains cross-cutting or high-risk architecture signals.",
                signals=tuple(signals),
                target_paths=targets,
                requires_coding_action=requires_coding_action,
            )

        standard_hits = [
            marker
            for marker in (
                "fastapi endpoint",
                "several files",
                "three files",
                "3 files",
                "medium bug",
                "regression bug",
                "多个文件",
                "中等错误",
            )
            if marker in lowered
        ]
        if len(targets) >= 3 or standard_hits:
            signals.extend(f"standard:{item}" for item in standard_hits)
            if len(targets) >= 3:
                signals.append("standard:three-or-more-targets")
            return TaskRoute(
                mode=ExecutionMode.STANDARD,
                reason="Request is bounded but needs coordinated multi-file work.",
                signals=tuple(signals),
                target_paths=targets,
                requires_coding_action=requires_coding_action,
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
        small_action = any(item in lowered for item in self._SMALL_ACTIONS)

        if (
            fast_scope
            or html_game
            or small_game
            or small_action
        ):
            if fast_scope:
                signals.append("small-scope-path")
            if html_game:
                signals.append("standalone-html-game")
            if small_game:
                signals.append("small-game-scope")
            if small_action:
                signals.append("small-local-action")
            return TaskRoute(
                mode=ExecutionMode.FAST,
                reason="Request is clearly local and bounded to a small artifact.",
                signals=tuple(signals),
                target_paths=targets,
                requires_coding_action=requires_coding_action,
            )

        return TaskRoute(
            mode=ExecutionMode.STANDARD,
            reason="No decisive fast-path or complex-task signal was found.",
            signals=("uncertain-medium-scope",),
            target_paths=targets,
            requires_coding_action=requires_coding_action,
        )

    @classmethod
    def _extract_paths(cls, text: str) -> list[str]:
        return [
            match.group(1).replace("\\", "/").rstrip(".,:;)")
            for match in cls._PATH.finditer(text)
        ]
