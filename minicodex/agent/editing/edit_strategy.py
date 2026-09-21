"""Deterministic, advisory edit-strategy selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EditStrategy:
    tool_name: str
    reason: str


class EditStrategyHint:
    """Recommend an edit primitive without making edits or choosing content."""

    def choose(
        self,
        *,
        target_path: str | None,
        file_exists: bool,
        symbol_known: bool = False,
        line_region_known: bool = False,
        exact_text_known: bool = False,
    ) -> EditStrategy:
        if not file_exists:
            return EditStrategy("write_file", "目标是新文件。")
        if symbol_known and str(target_path or "").lower().endswith(".py"):
            return EditStrategy("replace_symbol", "已知 Python 函数或类。")
        if line_region_known:
            return EditStrategy("replace_lines", "已知精确行范围。")
        if exact_text_known:
            return EditStrategy("patch_file", "已知小范围精确文本变更。")
        suffix = Path(str(target_path or "")).suffix
        return EditStrategy(
            "patch_file",
            f"先查看有界的当前区域，再对现有 {suffix or '文本'} 文件打补丁。",
        )

    def render(self, workspace, target_path: str | None) -> str:
        path = str(target_path or "").strip()
        exists = bool(path and (workspace / path).is_file())
        strategy = self.choose(target_path=path or None, file_exists=exists)
        return f"编辑策略：优先使用 {strategy.tool_name}。{strategy.reason}"
