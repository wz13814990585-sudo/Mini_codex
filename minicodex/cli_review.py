"""Terminal review of this task's checkpointed Agent edits."""

from __future__ import annotations

import difflib
import hashlib
from pathlib import Path

from .utils.paths import resolve_workspace_path


class ReviewConflict(RuntimeError):
    """The physical workspace no longer matches the Agent checkpoint chain."""


def checkpoint_diff(agent, workspace: str | Path, *, max_chars: int = 100_000) -> str:
    """Show only Agent-owned edits, including new files in a non-Git workspace."""

    manager = agent.checkpoint_manager
    if manager.history_trimmed:
        raise ReviewConflict("检查点历史已被裁剪，无法安全审查或整任务撤销。")
    root = Path(workspace).resolve()
    before = {}
    latest = {}
    for checkpoint in manager.all_checkpoints():
        if not checkpoint.sealed or checkpoint.rolled_back:
            continue
        path = checkpoint.snapshot.path
        before.setdefault(path, checkpoint.snapshot)
        latest[path] = checkpoint

    parts = []
    for path, snapshot in before.items():
        target = resolve_workspace_path(root, path)
        try:
            after = target.read_text(encoding="utf-8") if target.is_file() else ""
        except (OSError, UnicodeError) as exc:
            raise ReviewConflict(f"无法读取 {path}：{exc}") from exc
        actual_hash = hashlib.sha256(after.encode("utf-8")).hexdigest() if target.is_file() else None
        if actual_hash != latest[path].after_sha256:
            raise ReviewConflict(f"{path} 在 Agent 编辑后发生变化；未覆盖该外部修改。")
        parts.extend(difflib.unified_diff(
            (snapshot.content or "").splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}" if snapshot.existed else "/dev/null",
            tofile=f"b/{path}" if target.is_file() else "/dev/null",
        ))
    diff = "".join(parts)
    if len(diff) > max_chars:
        raise ReviewConflict("Diff 超过终端审查上限；请用 Git 或 UI 检查后手动处理。")
    return diff


def review_task(agent, workspace: str | Path, *, input_fn=None, print_fn=None) -> str:
    """Return accepted, rejected, no_edits, pending, or conflict."""

    ask = input_fn or input
    emit = print_fn or print
    try:
        diff = checkpoint_diff(agent, workspace)
    except (ReviewConflict, ValueError) as exc:
        emit(f"\n[审查冲突] {exc}")
        return "conflict"
    if not diff:
        emit("\n[审查] 没有可审查的 Agent 检查点改动。")
        return "no_edits"
    emit("\n[本次 Agent 改动]\n" + diff)
    while True:
        try:
            choice = ask("接受或撤销这些改动？[accept/reject，Ctrl-D 保留待处理] ").strip().casefold()
        except (EOFError, KeyboardInterrupt):
            emit("\n[审查] 改动已保留，尚未接受或撤销。")
            return "pending"
        if choice in {"accept", "a", "接受"}:
            emit("[审查] 已接受本次改动。")
            return "accepted"
        if choice in {"reject", "r", "撤销"}:
            result = agent.undo_task()
            if result.success:
                emit("[审查] 已撤销本次 Agent 的检查点改动。")
                return "rejected"
            emit(f"[审查冲突] {result.error or result.summary}")
            return "conflict"
        emit("请输入 accept 或 reject。")
