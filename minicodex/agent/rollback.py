from pathlib import Path

from .checkpoint import (
    Checkpoint,
    CheckpointManager,
)

from ..tools.edit_verifier import (
    EditVerifier,
)
from ..tools.paths import (
    resolve_workspace_path,
)
from ..tools.results import (
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
                    "Rollback failed because "
                    "the checkpoint does not exist."
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
                    "Unknown checkpoint."
                ),
            )

        # =====================================================
        # Not Sealed
        # =====================================================

        if not checkpoint.sealed:

            return ToolResult(
                success=False,
                summary=(
                    "Rollback failed because "
                    "the checkpoint was never sealed."
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
                    "Only checkpoints belonging "
                    "to successful edits can be "
                    "rolled back."
                ),
            )

        # =====================================================
        # Already Rolled Back
        # =====================================================

        if checkpoint.rolled_back:

            return ToolResult(
                success=False,
                summary=(
                    "Rollback failed because "
                    "this checkpoint has already "
                    "been rolled back."
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
                    "Checkpoint cannot be "
                    "rolled back twice."
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
                    "Rollback failed while "
                    "restoring the checkpoint."
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
                "Successfully rolled back "
                f"{checkpoint.snapshot.path} "
                "to its pre-edit checkpoint."
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
                    "Rollback was blocked because "
                    "the current file state no longer "
                    "matches the checkpoint."
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
                    "Expected the edited file to "
                    "exist before rollback."
                ),
            )

        if not file_path.is_file():

            return ToolResult(
                success=False,
                summary=(
                    "Rollback was blocked because "
                    "the target is no longer a file."
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
                    "Current path type changed."
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
                    "Rollback was blocked because "
                    "the file changed after this "
                    "checkpointed edit."
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
                    "Refusing to overwrite newer "
                    "workspace changes."
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
                    "Checkpoint says the file "
                    "existed but contains no "
                    "snapshot content."
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
                        "Cannot remove rollback "
                        "target because it is not "
                        "a file."
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
                        "Rollback verification failed."
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
                        "Restored file does not exist."
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
                        "Rollback verification failed."
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
                        "Restored file content "
                        "does not match snapshot."
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
                    "Rollback verification failed."
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
                    "File should have been removed "
                    "during rollback."
                ),
            )

        return None