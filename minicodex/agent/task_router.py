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
        r"change|remove|delete|write|improve|do|perform|complete)\b|"
        r"(创建|新增|添加|更新|修复|重构|重新设计|实现|构建|修改|改动|删除|编写|优化|做一个|完成)",
        re.IGNORECASE,
    )
    _INFORMATIONAL_LEAD = re.compile(
        r"^\s*(what|why|how (?:can|do|does|should)|explain|analy[sz]e|review|inspect|"
        r"tell me|介绍|解释|分析|检查|为什么|是什么|如何)\b",
        re.IGNORECASE,
    )

    def route(self, user_request: str, repo_state=None) -> TaskRoute:
        text = str(user_request or "").strip()
        lowered = text.casefold()
        targets = tuple(dict.fromkeys(self._extract_paths(text)))
        signals: list[str] = []
        requires_coding_action = self._requires_coding_action(text)

        score = 0

        def score_if(markers: tuple[str, ...], points: int, label: str) -> None:
            nonlocal score
            hits = [marker for marker in markers if marker in lowered]
            for hit in hits:
                score += points
                signals.append(f"score:{points:+d}:{label}:{hit}")

        score_if(("state machine", "状态机"), 3, "state-machine")
        score_if(("concurrency", "并发", "cancellation", "取消", "security", "安全", "multi-agent", "多智能体"), 3, "high-risk")
        score_if(("control plane", "控制平面", "migration", "迁移"), 2, "cross-cutting")
        score_if(("validation architecture", "rollback architecture", "memory architecture", "completion routing"), 2, "architecture-subsystem")
        if any(word in lowered for word in ("refactor", "redesign", "重构", "重新设计")) and any(
            word in lowered for word in ("architecture", "架构", "orchestration", "编排", "runtime", "运行时")
        ):
            score += 2
            signals.append("score:+2:architectural-change")

        # Runtime is deliberately not scored by itself: many small fixes use
        # that word without changing the agent/runtime architecture.
        if score >= 4:
            return TaskRoute(
                mode=ExecutionMode.COMPLEX,
                reason=f"Complexity score {score}: cross-cutting or high-risk change.",
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
            score += 3
            signals.append("score:+3:coordinated-multi-file")

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

        if fast_scope:
            score -= 3
            signals.append("score:-3:bounded-artifact")
        if html_game or small_game or small_action:
            score -= 2
            signals.append("score:-2:small-local-action")

        if score >= 4:
            mode = ExecutionMode.COMPLEX
            reason = f"Complexity score {score}: cross-cutting or high-risk change."
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

        if mode == ExecutionMode.FAST:
            if fast_scope:
                signals.append("small-scope-path")
            if html_game:
                signals.append("standalone-html-game")
            if small_game:
                signals.append("small-game-scope")
            if small_action:
                signals.append("small-local-action")
        return TaskRoute(
            mode=mode,
            reason=reason,
            signals=tuple(signals),
            target_paths=targets,
            requires_coding_action=requires_coding_action,
        )

    def _requires_coding_action(self, text: str) -> bool:
        if not self._CODING_ACTION.search(text):
            return False
        if self._INFORMATIONAL_LEAD.search(text):
            explicit_request = re.search(
                r"\b(please|go ahead and|now)\s+(create|add|update|fix|refactor|implement|modify|change)\b|"
                r"(请|现在)(帮我)?(创建|添加|更新|修复|重构|实现|修改|优化)",
                text,
                re.IGNORECASE,
            )
            return bool(explicit_request)
        return True

    @classmethod
    def _extract_paths(cls, text: str) -> list[str]:
        return [
            match.group(1).replace("\\", "/").rstrip(".,:;)")
            for match in cls._PATH.finditer(text)
        ]
