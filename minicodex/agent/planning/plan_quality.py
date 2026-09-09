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
        return process_count >= 1 or any(
            issue.code in {"broad_semantic", "too_many_steps", "repeated_verification"}
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
        r"^\s*(inspect|read|search|review|check|verify|confirm|validate|test|run tests)\b|"
        r"^\s*(检查|读取|搜索|审查|查看|确认|验证|测试|再次验证)",
        re.IGNORECASE,
    )
    _VERIFICATION = re.compile(
        r"\b(check|verify|confirm|validate|test)\b|检查|确认|验证|测试",
        re.IGNORECASE,
    )

    def __init__(self, max_steps: int = 6):
        self.max_steps = max(1, int(max_steps))

    def validate(self, steps: list) -> PlanQualityReport:
        issues: list[PlanQualityIssue] = []
        self.normalize(steps)

        if len(steps) > self.max_steps:
            issues.append(
                PlanQualityIssue(
                    step_id=steps[self.max_steps].id,
                    code="too_many_steps",
                    message=f"Plan exceeds the {self.max_steps}-step limit.",
                )
            )

        verification_steps = [
            step
            for step in steps
            if self._VERIFICATION.search(str(getattr(step, "description", "")))
            and not getattr(step, "acceptance_criteria", None)
        ]
        for step in verification_steps[1:]:
            issues.append(
                PlanQualityIssue(
                    step_id=step.id,
                    code="repeated_verification",
                    message="Repeated verification belongs in one outcome milestone.",
                )
            )

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


# Public concise name for the plan quality normalizer.
PlanNormalizer = PlanQualityValidator
