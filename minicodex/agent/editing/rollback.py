from pathlib import Path

from .checkpoint import (
    Checkpoint,
    CheckpointManager,
)

from .edit_verifier import (
    EditVerifier,
)
from ...utils.paths import (
    resolve_workspace_path,
)
from ...tools.results import (
    ToolResult,
)


# =============================================================
# Rollback Engine
# =============================================================


class RollbackEngine:
    """
    Deterministically restore one sealed checkpoint.

    Safety rules:

    1. Checkpoint must exist.
    2. Checkpoint must be sealed.
    3. Checkpoint must not already be rolled back.
    4. Current physical file must still match the
       checkpoint's recorded after-state.
    5. Restore the exact before-state.
    6. Verify restoration physically.

    It does NOT decide whether rollback is desirable.
    """

    def __init__(
        self,
        *,
        workspace: str | Path,
        checkpoint_manager: (
            CheckpointManager
        ),
    ):

        self.workspace = (
            Path(
                workspace
            )
            .resolve()
        )

        self.checkpoint_manager = (
            checkpoint_manager
        )

    # =========================================================
    # Rollback
    # =========================================================

    def undo_task(self) -> ToolResult:
        """Undo only this task's checkpoint chain, never a Git reset."""
        manager = self.checkpoint_manager
        if manager.history_trimmed:
            return ToolResult(False, "任务撤销不可用：检查点历史已被裁剪", {})
        checkpoints = [c for c in manager.all_checkpoints() if c.sealed and not c.rolled_back]
        expected = {}
        for checkpoint in reversed(checkpoints):
            path = checkpoint.snapshot.path
            if path not in expected:
                file_path = resolve_workspace_path(self.workspace, path)
                conflict = self._check_current_state(checkpoint, file_path)
                if conflict is not None:
                    return conflict
            elif expected[path] != checkpoint.after_sha256:
                return ToolResult(False, "智能体编辑之间存在并发变更，无法整任务撤销",
                                  {"path": path, "failure_type": "rollback_conflict"})
            expected[path] = checkpoint.snapshot.sha256
        restored = []
        for checkpoint in reversed(checkpoints):
            result = self.rollback(checkpoint.checkpoint_id)
            if not result.success:
                result.data["restored_paths"] = restored
                return result
            restored.append(checkpoint.snapshot.path)
        return ToolResult(True, "任务编辑已恢复到任务开始前的精确内容",
                          {"restored_paths": list(dict.fromkeys(restored))})

    def rollback(
        self,
        checkpoint_id: str,
    ) -> ToolResult:

        checkpoint = (
            self.checkpoint_manager
            .get(
                checkpoint_id
            )
        )

        # =====================================================
        # Missing Checkpoint
        # =====================================================

        if checkpoint is None:

            return ToolResult(
                success=False,
                summary=(
                    "回滚失败：检查点不存在。"
                ),
                data={
                    "checkpoint_id": (
                        checkpoint_id
                    ),
                    "failure_type": (
                        "checkpoint_not_found"
                    ),
                },
                error=(
                    "未知检查点。"
                ),
            )

        # =====================================================
        # Not Sealed
        # =====================================================

        if not checkpoint.sealed:

            return ToolResult(
                success=False,
                summary=(
                    "回滚失败：检查点从未封存。"
                ),
                data={
                    "checkpoint_id": (
                        checkpoint
                        .checkpoint_id
                    ),
                    "failure_type": (
                        "checkpoint_unsealed"
                    ),
                },
                error=(
                    "只能回滚属于成功编辑的检查点。"
                ),
            )

        # =====================================================
        # Already Rolled Back
        # =====================================================

        if checkpoint.rolled_back:

            return ToolResult(
                success=False,
                summary=(
                    "回滚失败：该检查点已被回滚。"
                ),
                data={
                    "checkpoint_id": (
                        checkpoint
                        .checkpoint_id
                    ),
                    "failure_type": (
                        "checkpoint_already_rolled_back"
                    ),
                },
                error=(
                    "检查点不能被回滚两次。"
                ),
            )

        file_path = (
            resolve_workspace_path(
                self.workspace,
                checkpoint
                .snapshot
                .path,
            )
        )

        # =====================================================
        # Stale Rollback Guard
        # =====================================================

        stale_result = (
            self._check_current_state(
                checkpoint,
                file_path,
            )
        )

        if (
            stale_result
            is not None
        ):

            return stale_result

        # =====================================================
        # Restore Before-State
        # =====================================================

        try:

            if (
                checkpoint
                .snapshot
                .existed
            ):

                self._restore_existing_file(
                    checkpoint,
                    file_path,
                )

            else:

                self._restore_missing_file(
                    file_path
                )

        except Exception as e:

            return ToolResult(
                success=False,
                summary=(
                    "恢复检查点时回滚失败。"
                ),
                data={
                    "checkpoint_id": (
                        checkpoint
                        .checkpoint_id
                    ),
                    "path": (
                        checkpoint
                        .snapshot
                        .path
                    ),
                    "failure_type": (
                        "rollback_write"
                    ),
                },
                error=(
                    f"{type(e).__name__}: "
                    f"{e}"
                ),
            )

        # =====================================================
        # Verify Physical Restore
        # =====================================================

        verification_error = (
            self._verify_restore(
                checkpoint,
                file_path,
            )
        )

        if (
            verification_error
            is not None
        ):

            return verification_error

        # =====================================================
        # Mark Lifecycle
        # =====================================================

        (
            self.checkpoint_manager
            .mark_rolled_back(
                checkpoint
                .checkpoint_id
            )
        )

        return ToolResult(
            success=True,
            summary=(
                f"已成功将 {checkpoint.snapshot.path} "
                "回滚到编辑前的检查点。"
            ),
            data={
                "checkpoint_id": (
                    checkpoint
                    .checkpoint_id
                ),
                "edit_revision": (
                    checkpoint
                    .edit_revision
                ),
                "path": (
                    checkpoint
                    .snapshot
                    .path
                ),
                "restored_existing_file": (
                    checkpoint
                    .snapshot
                    .existed
                ),
                "removed_created_file": (
                    not checkpoint
                    .snapshot
                    .existed
                ),
                "restored_sha256": (
                    checkpoint
                    .snapshot
                    .sha256
                ),
            },
        )

    # =========================================================
    # Current-State Guard
    # =========================================================

    def _check_current_state(
        self,
        checkpoint: Checkpoint,
        file_path: Path,
    ) -> ToolResult | None:

        if not file_path.exists():

            return ToolResult(
                success=False,
                summary=(
                    "回滚被阻止：当前文件状态已与检查点不一致。"
                ),
                data={
                    "checkpoint_id": (
                        checkpoint
                        .checkpoint_id
                    ),
                    "path": (
                        checkpoint
                        .snapshot
                        .path
                    ),
                    "failure_type": (
                        "stale_rollback"
                    ),
                },
                error=(
                    "回滚前期望已编辑文件仍然存在。"
                ),
            )

        if not file_path.is_file():

            return ToolResult(
                success=False,
                summary=(
                    "回滚被阻止：目标已不再是文件。"
                ),
                data={
                    "checkpoint_id": (
                        checkpoint
                        .checkpoint_id
                    ),
                    "path": (
                        checkpoint
                        .snapshot
                        .path
                    ),
                    "failure_type": (
                        "stale_rollback"
                    ),
                },
                error=(
                    "当前路径类型已改变。"
                ),
            )

        current_content = (
            file_path.read_text(
                encoding="utf-8"
            )
        )

        current_sha256 = (
            EditVerifier
            .content_hash(
                current_content
            )
        )

        if (
            current_sha256
            != checkpoint.after_sha256
        ):

            return ToolResult(
                success=False,
                summary=(
                    "回滚被阻止：此检查点编辑之后文件又发生了变化。"
                ),
                data={
                    "checkpoint_id": (
                        checkpoint
                        .checkpoint_id
                    ),
                    "path": (
                        checkpoint
                        .snapshot
                        .path
                    ),
                    "failure_type": (
                        "stale_rollback"
                    ),
                    "expected_after_sha256": (
                        checkpoint
                        .after_sha256
                    ),
                    "current_sha256": (
                        current_sha256
                    ),
                },
                error=(
                    "拒绝覆盖工作区中更新的变更。"
                ),
            )

        return None

    # =========================================================
    # Restore Existing File
    # =========================================================

    @staticmethod
    def _restore_existing_file(
        checkpoint: Checkpoint,
        file_path: Path,
    ) -> None:

        content = (
            checkpoint
            .snapshot
            .content
        )

        if (
            content
            is None
        ):

            raise ValueError(
                (
                    "检查点声称文件曾存在，但快照内容为空。"
                )
            )

        file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        file_path.write_text(
            content,
            encoding="utf-8",
        )

    # =========================================================
    # Restore Missing File
    # =========================================================

    @staticmethod
    def _restore_missing_file(
        file_path: Path,
    ) -> None:

        if file_path.exists():

            if not file_path.is_file():

                raise ValueError(
                    (
                        "无法删除回滚目标：它不是文件。"
                    )
                )

            file_path.unlink()

    # =========================================================
    # Verify Restore
    # =========================================================

    @staticmethod
    def _verify_restore(
        checkpoint: Checkpoint,
        file_path: Path,
    ) -> ToolResult | None:

        # =====================================================
        # Original File Existed
        # =====================================================

        if (
            checkpoint
            .snapshot
            .existed
        ):

            if not file_path.exists():

                return ToolResult(
                    success=False,
                    summary=(
                        "回滚校验失败。"
                    ),
                    data={
                        "checkpoint_id": (
                            checkpoint
                            .checkpoint_id
                        ),
                        "failure_type": (
                            "rollback_verification"
                        ),
                    },
                    error=(
                        "恢复后的文件不存在。"
                    ),
                )

            restored_content = (
                file_path.read_text(
                    encoding="utf-8"
                )
            )

            restored_sha256 = (
                EditVerifier
                .content_hash(
                    restored_content
                )
            )

            if (
                restored_sha256
                != checkpoint
                .snapshot
                .sha256
            ):

                return ToolResult(
                    success=False,
                    summary=(
                        "回滚校验失败。"
                    ),
                    data={
                        "checkpoint_id": (
                            checkpoint
                            .checkpoint_id
                        ),
                        "failure_type": (
                            "rollback_verification"
                        ),
                        "expected_sha256": (
                            checkpoint
                            .snapshot
                            .sha256
                        ),
                        "actual_sha256": (
                            restored_sha256
                        ),
                    },
                    error=(
                        "恢复后的文件内容与快照不一致。"
                    ),
                )

            return None

        # =====================================================
        # Original File Did Not Exist
        # =====================================================

        if file_path.exists():

            return ToolResult(
                success=False,
                summary=(
                    "回滚校验失败。"
                ),
                data={
                    "checkpoint_id": (
                        checkpoint
                        .checkpoint_id
                    ),
                    "failure_type": (
                        "rollback_verification"
                    ),
                },
                error=(
                    "回滚期间本应删除该文件。"
                ),
            )

        return None
