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
            return EditStrategy("write_file", "The requested target is a new file.")
        if symbol_known and str(target_path or "").lower().endswith(".py"):
            return EditStrategy("replace_symbol", "A Python function or class is known.")
        if line_region_known:
            return EditStrategy("replace_lines", "A precise line region is known.")
        if exact_text_known:
            return EditStrategy("patch_file", "A small exact text change is known.")
        suffix = Path(str(target_path or "")).suffix
        return EditStrategy(
            "patch_file",
            f"Inspect a bounded current region, then patch the existing {suffix or 'text'} file.",
        )

    def render(self, workspace, target_path: str | None) -> str:
        path = str(target_path or "").strip()
        exists = bool(path and (workspace / path).is_file())
        strategy = self.choose(target_path=path or None, file_exists=exists)
        return f"Edit strategy: prefer {strategy.tool_name}. {strategy.reason}"
