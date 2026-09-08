"""Classify what kind of product behavior a request authorizes."""

from __future__ import annotations

from enum import Enum
import re


class TaskIntent(str, Enum):
    INFORMATIONAL = "informational"
    INSPECT_ONLY = "inspect_only"
    MODIFY = "modify"


class IntentClassifier:
    """Deterministic intent rules independent from task complexity."""

    _NO_EDIT = re.compile(
        r"\b(?:do not|don't|dont|without)\s+(?:change|modify|edit|write)(?:ing)?\b|"
        r"(?:不要|无需|不需要)(?:修改|改动|编辑|写入)",
        re.IGNORECASE,
    )
    _HOW_TO = re.compile(
        r"^\s*(?:explain\s+how|tell me how|how (?:can|do|should) i|"
        r"请?(?:解释|告诉我).*(?:如何|怎么))",
        re.IGNORECASE,
    )
    _MODIFY = re.compile(
        r"\b(?:create|add|update|fix|refactor|redesign|implement|build|modify|"
        r"change|remove|delete|write|improve|perform|complete|rename)\b|"
        r"(?:创建|新增|添加|更新|修复|重构|重新设计|实现|构建|修改|改动|删除|编写|优化|完成)",
        re.IGNORECASE,
    )
    _DO_TASK = re.compile(r"^\s*do\s+(?:a|the|this)\b", re.IGNORECASE)
    _INSPECT = re.compile(
        r"\b(?:review|inspect|analy[sz]e|look at|check)\b|"
        r"(?:审查|检查|分析|看一下|看看)",
        re.IGNORECASE,
    )
    _REPO_REFERENCE = re.compile(
        r"(?:[\w.-]+[/\\])+[\w.-]+|[\w.-]+\.(?:py|js|ts|html|css|md|json|ya?ml|toml)\b",
        re.IGNORECASE,
    )

    def classify(self, user_request: str) -> TaskIntent:
        text = str(user_request or "").strip()
        if self._NO_EDIT.search(text):
            return TaskIntent.INSPECT_ONLY
        if self._HOW_TO.search(text):
            return TaskIntent.INFORMATIONAL
        if self._MODIFY.search(text) or self._DO_TASK.search(text):
            return TaskIntent.MODIFY
        if self._INSPECT.search(text):
            return TaskIntent.INSPECT_ONLY
        if re.match(r"^\s*explain\b", text, re.IGNORECASE) and self._REPO_REFERENCE.search(text):
            return TaskIntent.INSPECT_ONLY
        return TaskIntent.INFORMATIONAL
