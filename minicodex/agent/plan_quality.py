"""Lightweight deterministic checks for overly broad plan steps."""

from __future__ import annotations

import re


class PlanNormalizer:
    """Annotate broad semantic steps without guessing how to split them."""

    _ACTION_WORDS = re.compile(
        r"\b(add|build|create|implement|update|fix|handle|support|"
        r"validate|render|move|rotate|lock|clear|score|restart|start|"
        r"pause|accelerate)\b|"
        r"(添加|实现|更新|修复|处理|支持|渲染|移动|旋转|锁定|消除|"
        r"计分|重启|开始|暂停|加速)",
        re.IGNORECASE,
    )
    _SEPARATORS = re.compile(r",|;|，|；|、|\band\b|以及|并且|同时")

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
