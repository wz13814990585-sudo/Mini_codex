"""Lightweight deterministic checks for overly broad plan steps."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class PlanQualityIssue:
    step_id: int
    code: str
    message: str


@dataclass(frozen=True)
class PlanQualityReport:
    issues: tuple[PlanQualityIssue, ...]

    @property
    def should_regenerate(self) -> bool:
        process_count = sum(
            issue.code == "process_only"
            for issue in self.issues
        )
        return process_count >= 2 or any(
            issue.code == "broad_semantic"
            for issue in self.issues
        )

    @property
    def has_process_only_steps(self) -> bool:
        return any(issue.code == "process_only" for issue in self.issues)


class PlanQualityValidator:
    """Detect non-outcome plans while leaving semantic splitting to the LLM."""

    _ACTION_WORDS = re.compile(
        r"\b(add|build|create|implement|update|fix|handle|support|"
        r"validate|render|move|rotate|lock|clear|score|restart|start|"
        r"pause|accelerate)\b|"
        r"(添加|实现|更新|修复|处理|支持|渲染|移动|旋转|锁定|消除|"
        r"计分|重启|开始|暂停|加速)",
        re.IGNORECASE,
    )
    _SEPARATORS = re.compile(r",|;|，|；|、|\band\b|以及|并且|同时")
    _PROCESS_ONLY = re.compile(
        r"^\s*(inspect|read|search|review|check|verify|confirm)\b|"
        r"^\s*(检查|读取|搜索|审查|查看|确认|再次验证)",
        re.IGNORECASE,
    )

    def validate(self, steps: list) -> PlanQualityReport:
        issues: list[PlanQualityIssue] = []
        self.normalize(steps)

        for step in steps:
            criteria = list(getattr(step, "acceptance_criteria", []) or [])
            description = str(getattr(step, "description", ""))
            if not criteria and self._PROCESS_ONLY.search(description):
                issues.append(
                    PlanQualityIssue(
                        step_id=step.id,
                        code="process_only",
                        message=(
                            "Plan steps must describe an outcome, not only "
                            "inspection or confirmation activity."
                        ),
                    )
                )
            elif getattr(step, "requires_semantic_completion", False):
                issues.append(
                    PlanQualityIssue(
                        step_id=step.id,
                        code="broad_semantic",
                        message=step.quality_warnings[0],
                    )
                )

        return PlanQualityReport(tuple(issues))

    def normalize(self, steps: list) -> list:
        for step in steps:
            criteria = list(
                getattr(step, "acceptance_criteria", []) or []
            )
            if criteria:
                continue

            description = str(getattr(step, "description", ""))
            action_count = len(self._ACTION_WORDS.findall(description))
            separator_count = len(self._SEPARATORS.findall(description))
            if action_count >= 5 or separator_count >= 4:
                step.requires_semantic_completion = True
                warning = (
                    "Broad step has no machine-checkable acceptance criteria; "
                    "it requires explicit semantic completion and will not be "
                    "auto-completed by inspection evidence."
                )
                if warning not in step.quality_warnings:
                    step.quality_warnings.append(warning)

        return steps


# Backward-compatible name retained for callers from Control Plane V1.
PlanNormalizer = PlanQualityValidator
