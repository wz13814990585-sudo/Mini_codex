"""Interpret task-level edit prohibitions without losing their scope."""

from __future__ import annotations

import re


_EXTERNAL_WORKSPACE_ONLY = re.compile(
    r"(?:"
    r"(?:不要|不允许|无需|不需要)\s*(?:修改|改动|编辑|写入)\s*"
    r"(?:任何|所有)?\s*(?:当前|本)?(?:工作区|项目|仓库)\s*"
    r"(?:以外|之外|外)\s*(?:的)?\s*(?:文件|代码|内容)?|"
    r"\b(?:do not|don't|dont|without)\s+"
    r"(?:change|modify|edit|write)(?:ing)?\s+"
    r"(?:any\s+)?(?:files?|code)\s+outside\s+"
    r"(?:the\s+)?(?:workspace|project|repository)\b"
    r")"
    r"(?=\s*(?:[，,。.;；!?！]|$))",
    re.IGNORECASE,
)

_GLOBAL_NO_EDIT = re.compile(
    r"\b(?:do not|don't|dont|without)\s+(?:change|modify|edit|write)(?:ing)?\b|"
    r"(?:不要|无需|不需要|不允许)(?:修改|改动|编辑|写入)",
    re.IGNORECASE,
)


def has_global_no_edit_constraint(request: str) -> bool:
    """Only a global no-edit instruction revokes permission for all edits.

    The workspace boundary is enforced independently by file tools. A user
    saying "do not edit outside the workspace" must not turn a creation task
    inside that workspace into a read-only task.
    """

    remaining = _EXTERNAL_WORKSPACE_ONLY.sub("", str(request or ""))
    return _GLOBAL_NO_EDIT.search(remaining) is not None
