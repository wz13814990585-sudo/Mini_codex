from dataclasses import dataclass
from pathlib import Path

from ..tools.edit_verifier import (
    EditVerifier,
)
from ..tools.paths import (
    resolve_workspace_path,
)


# =============================================================
# File Snapshot
# =============================================================


@dataclass(frozen=True)
class FileSnapshot:
    """
    Immutable before-state of one workspace file.
    """

    path: str

    existed: bool

    content: str | None

    sha256: str | None


# =============================================================
# Checkpoint
# =============================================================


@dataclass
class Checkpoint:
    """
    One file-level edit checkpoint.

    snapshot:
        State BEFORE the protected edit.

    after_sha256:
        State AFTER the protected edit succeeds.

    sealed:
        True only after the edit actually succeeds and
        its resulting physical state has been recorded.

    rolled_back:
        True after the checkpoint has been successfully
        restored.
    """

    checkpoint_id: str

    edit_revision: int

    snapshot: FileSnapshot

    after_sha256: str | None = None

    sealed: bool = False

    rolled_back: bool = False


# =============================================================
# Checkpoint Manager
# =============================================================


class CheckpointManager:
    """
    Deterministic in-memory checkpoint store.

    Responsibilities:

    - capture before-state
    - record after-state after a successful edit
    - preserve bounded checkpoint history
    - discard failed edits
    - track rollback lifecycle

    It does NOT decide when rollback should happen.
    """

    def __init__(
        self,
        workspace: str | Path = ".",
        max_checkpoints: int = 50,
    ):

        if (
            max_checkpoints
            < 1
        ):

            raise ValueError(
                "max_checkpoints must be >= 1."
            )

        self.workspace = (
            Path(
                workspace
            )
            .resolve()
        )

        self.max_checkpoints = (
            max_checkpoints
        )

        self._counter = 0

        self._checkpoints: list[
            Checkpoint
        ] = []

    # =========================================================
    # Reset
    # =========================================================

    def reset(
        self,
    ) -> None:

        self._counter = 0

        self._checkpoints.clear()

    # =========================================================
    # Capture Before-State
    # =========================================================

    def capture(
        self,
        *,
        path: str,
        edit_revision: int,
    ) -> Checkpoint:

        normalized_path = (
            str(
                path
            )
            .strip()
        )

        if not normalized_path:

            raise ValueError(
                "Checkpoint path cannot be empty."
            )

        if (
            edit_revision
            < 1
        ):

            raise ValueError(
                "edit_revision must be >= 1."
            )

        file_path = (
            resolve_workspace_path(
                self.workspace,
                normalized_path,
            )
        )

        # =====================================================
        # Existing File
        # =====================================================

        if file_path.exists():

            if not file_path.is_file():

                raise ValueError(
                    (
                        "Checkpoint target is not "
                        f"a file: {normalized_path}"
                    )
                )

            content = (
                file_path.read_text(
                    encoding="utf-8"
                )
            )

            snapshot = (
                FileSnapshot(
                    path=normalized_path,
                    existed=True,
                    content=content,
                    sha256=(
                        EditVerifier
                        .content_hash(
                            content
                        )
                    ),
                )
            )

        # =====================================================
        # Missing File
        # =====================================================

        else:

            snapshot = (
                FileSnapshot(
                    path=normalized_path,
                    existed=False,
                    content=None,
                    sha256=None,
                )
            )

        # =====================================================
        # Create Checkpoint
        # =====================================================

        self._counter += 1

        checkpoint = (
            Checkpoint(
                checkpoint_id=(
                    f"cp-{self._counter:06d}"
                ),
                edit_revision=(
                    edit_revision
                ),
                snapshot=(
                    snapshot
                ),
            )
        )

        self._checkpoints.append(
            checkpoint
        )

        self._trim_history()

        return checkpoint

    # =========================================================
    # Seal After Successful Edit
    # =========================================================

    def seal(
        self,
        checkpoint_id: str,
    ) -> Checkpoint:
        """
        Record the physical after-state created by the edit.

        A checkpoint must be sealed before it is eligible
        for rollback.
        """

        checkpoint = (
            self.get(
                checkpoint_id
            )
        )

        if checkpoint is None:

            raise ValueError(
                (
                    "Checkpoint not found: "
                    f"{checkpoint_id}"
                )
            )

        if checkpoint.rolled_back:

            raise ValueError(
                (
                    "Cannot seal a checkpoint "
                    "that has already been rolled back."
                )
            )

        file_path = (
            resolve_workspace_path(
                self.workspace,
                checkpoint.snapshot.path,
            )
        )

        if not file_path.exists():

            # An edit tool reporting success while leaving
            # no physical file is inconsistent for the edit
            # tools currently protected by this manager.
            raise ValueError(
                (
                    "Cannot seal checkpoint because "
                    "the edited file does not exist: "
                    f"{checkpoint.snapshot.path}"
                )
            )

        if not file_path.is_file():

            raise ValueError(
                (
                    "Cannot seal checkpoint because "
                    "the edited path is not a file: "
                    f"{checkpoint.snapshot.path}"
                )
            )

        content = (
            file_path.read_text(
                encoding="utf-8"
            )
        )

        checkpoint.after_sha256 = (
            EditVerifier
            .content_hash(
                content
            )
        )

        checkpoint.sealed = True

        return checkpoint

    # =========================================================
    # Mark Rolled Back
    # =========================================================

    def mark_rolled_back(
        self,
        checkpoint_id: str,
    ) -> Checkpoint:

        checkpoint = (
            self.get(
                checkpoint_id
            )
        )

        if checkpoint is None:

            raise ValueError(
                (
                    "Checkpoint not found: "
                    f"{checkpoint_id}"
                )
            )

        checkpoint.rolled_back = True

        return checkpoint

    # =========================================================
    # Discard
    # =========================================================

    def discard(
        self,
        checkpoint_id: str,
    ) -> bool:

        target = (
            str(
                checkpoint_id
            )
            .strip()
        )

        if not target:

            return False

        for index in range(
            len(
                self._checkpoints
            )
            - 1,
            -1,
            -1,
        ):

            checkpoint = (
                self._checkpoints[
                    index
                ]
            )

            if (
                checkpoint.checkpoint_id
                == target
            ):

                del self._checkpoints[
                    index
                ]

                return True

        return False

    # =========================================================
    # Latest
    # =========================================================

    def latest(
        self,
    ) -> Checkpoint | None:

        if not self._checkpoints:

            return None

        return (
            self._checkpoints[-1]
        )

    # =========================================================
    # Get
    # =========================================================

    def get(
        self,
        checkpoint_id: str,
    ) -> Checkpoint | None:

        target = (
            str(
                checkpoint_id
            )
            .strip()
        )

        for checkpoint in reversed(
            self._checkpoints
        ):

            if (
                checkpoint.checkpoint_id
                == target
            ):

                return checkpoint

        return None

    # =========================================================
    # Latest For Path
    # =========================================================

    def latest_for_path(
        self,
        path: str,
    ) -> Checkpoint | None:

        normalized = (
            str(
                path
            )
            .strip()
        )

        for checkpoint in reversed(
            self._checkpoints
        ):

            if (
                checkpoint.snapshot.path
                == normalized
            ):

                return checkpoint

        return None

    # =========================================================
    # Latest For Revision
    # =========================================================

    def latest_for_revision(
        self,
        edit_revision: int,
    ) -> Checkpoint | None:

        for checkpoint in reversed(
            self._checkpoints
        ):

            if (
                checkpoint.edit_revision
                == edit_revision
            ):

                return checkpoint

        return None

    # =========================================================
    # History
    # =========================================================

    def all_checkpoints(
        self,
    ) -> tuple[
        Checkpoint,
        ...
    ]:

        return tuple(
            self._checkpoints
        )

    # =========================================================
    # Trim History
    # =========================================================

    def _trim_history(
        self,
    ) -> None:

        if (
            len(
                self._checkpoints
            )
            <= self.max_checkpoints
        ):

            return

        overflow = (
            len(
                self._checkpoints
            )
            - self.max_checkpoints
        )

        del self._checkpoints[
            :overflow
        ]