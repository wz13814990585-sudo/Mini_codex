from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING
from pathlib import Path

from .checkpoint import (
    CheckpointManager,
)
from ..runtime.tool_types import (
    PreparedToolCall,
    ToolExecution,
)
if TYPE_CHECKING:
    from ..runtime.tool_executor import ToolExecutor

from ...tools.results import (
    ToolResult,
)


CHECKPOINTED_EDIT_TOOLS = {
    "patch_file",
    "replace_lines",
    "replace_symbol",
    "write_file",
}


class CheckpointingToolExecutor:

    def __init__(
        self,
        *,
        executor: ToolExecutor,
        checkpoint_manager: CheckpointManager,
        next_edit_revision: Callable[
            [],
            int,
        ],
        on_successful_edit: (
            Callable[
                [str],
                None,
            ]
            | None
        ) = None,
    ):

        self.executor = (
            executor
        )

        self.checkpoint_manager = (
            checkpoint_manager
        )

        self.next_edit_revision = (
            next_edit_revision
        )

        self.on_successful_edit = (
            on_successful_edit
        )

    # =========================================================
    # Prepare
    # =========================================================

    def prepare(
        self,
        tool_name: str,
        raw_arguments: str,
    ) -> PreparedToolCall:

        return (
            self.executor
            .prepare(
                tool_name=tool_name,
                raw_arguments=raw_arguments,
            )
        )

    # =========================================================
    # Execute
    # =========================================================

    def execute_prepared(
        self,
        prepared: PreparedToolCall,
    ) -> ToolExecution:

        # =====================================================
        # Preparation Already Failed
        # =====================================================

        if (
            prepared.error
            is not None
        ):

            return (
                self.executor
                .execute_prepared(
                    prepared
                )
            )

        # =====================================================
        # Non Edit Tool
        # =====================================================

        if (
            prepared.tool_name
            not in CHECKPOINTED_EDIT_TOOLS
        ):

            return (
                self.executor
                .execute_prepared(
                    prepared
                )
            )

        # =====================================================
        # Explicit Physical Target
        # =====================================================

        path_value = (
            prepared.arguments
            .get(
                "path"
            )
        )

        if (
            path_value
            is None
            or not str(
                path_value
            ).strip()
        ):

            return ToolExecution(
                tool_name=(
                    prepared.tool_name
                ),
                arguments=(
                    prepared.arguments
                ),
                result=ToolResult(
                    success=False,
                    summary=(
                        f"Edit tool "
                        f"'{prepared.tool_name}' "
                        "was blocked because no "
                        "explicit target path was "
                        "provided."
                    ),
                    data={
                        "tool_name": (
                            prepared.tool_name
                        ),
                        "failure_type": (
                            "checkpoint_precondition"
                        ),
                    },
                    error=(
                        "Safe edit execution requires "
                        "an explicit 'path'."
                    ),
                ),
            )

        path = (
            str(
                path_value
            )
            .strip()
        )

        # =====================================================
        # Determine Next Revision
        # =====================================================

        try:

            edit_revision = int(
                self.next_edit_revision()
            )

        except Exception as e:

            return (
                self._checkpoint_failure(
                    prepared=prepared,
                    failure_type=(
                        "checkpoint_revision"
                    ),
                    summary=(
                        "Edit was blocked because "
                        "the next edit revision "
                        "could not be determined."
                    ),
                    error=e,
                )
            )

        if (
            edit_revision
            < 1
        ):

            return ToolExecution(
                tool_name=(
                    prepared.tool_name
                ),
                arguments=(
                    prepared.arguments
                ),
                result=ToolResult(
                    success=False,
                    summary=(
                        "Edit was blocked because "
                        "the next edit revision "
                        "was invalid."
                    ),
                    data={
                        "tool_name": (
                            prepared.tool_name
                        ),
                        "failure_type": (
                            "checkpoint_revision"
                        ),
                        "edit_revision": (
                            edit_revision
                        ),
                    },
                    error=(
                        "Next edit revision "
                        "must be >= 1."
                    ),
                ),
            )

        # =====================================================
        # Capture Before State
        # =====================================================

        try:

            checkpoint = (
                self.checkpoint_manager
                .capture(
                    path=path,
                    edit_revision=(
                        edit_revision
                    ),
                )
            )

        except Exception as e:

            return (
                self._checkpoint_failure(
                    prepared=prepared,
                    failure_type=(
                        "checkpoint_capture"
                    ),
                    summary=(
                        f"Edit tool "
                        f"'{prepared.tool_name}' "
                        "was blocked because a "
                        "pre-edit checkpoint could "
                        "not be created."
                    ),
                    error=e,
                    path=path,
                )
            )

        # Detect a concurrent user/IDE write between snapshot capture and the
        # physical edit. Rebuild against current truth instead of overwriting it.
        file_path = Path(self.checkpoint_manager.workspace) / path
        current_hash = None
        try:
            if file_path.is_file():
                from .edit_verifier import EditVerifier
                current_hash = EditVerifier.content_hash(file_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            current_hash = "__unreadable__"
        if current_hash != checkpoint.snapshot.sha256:
            self.checkpoint_manager.discard(checkpoint.checkpoint_id)
            return ToolExecution(
                tool_name=prepared.tool_name,
                arguments=prepared.arguments,
                result=ToolResult(
                    success=False,
                    summary=f"Edit conflict detected for {path}; the file changed after inspection.",
                    data={
                        "path": path, "failure_type": "workspace_conflict",
                        "expected_sha256": checkpoint.snapshot.sha256,
                        "current_sha256": current_hash,
                        "retry_action": "read_current_file_then_rebuild_edit",
                    },
                    error="Concurrent workspace modification prevented the edit.",
                ),
            )

        # =====================================================
        # Execute Physical Edit
        # =====================================================

        execution = (
            self.executor
            .execute_prepared(
                prepared
            )
        )

        result = (
            execution.result
        )

        # =====================================================
        # Physical Edit Failed
        # =====================================================

        if not (
            result.success
        ):

            self.checkpoint_manager.discard(
                checkpoint
                .checkpoint_id
            )

            return execution

        # =====================================================
        # Physical Edit Succeeded
        #
        # From this point onward:
        #
        # result.success MUST remain True.
        #
        # The filesystem has already changed.
        # =====================================================

        checkpoint_sealed = False

        checkpoint_error = None

        sealed = None

        try:

            sealed = (
                self.checkpoint_manager
                .seal(
                    checkpoint
                    .checkpoint_id
                )
            )

            checkpoint_sealed = True

        except Exception as e:

            checkpoint_error = (
                f"{type(e).__name__}: "
                f"{e}"
            )

            # An unsealed checkpoint must never later be
            # mistaken for a valid rollback candidate.
            self.checkpoint_manager.discard(
                checkpoint
                .checkpoint_id
            )

        # =====================================================
        # Common Edit Metadata
        # =====================================================

        result.data[
            "checkpoint_id"
        ] = (
            checkpoint
            .checkpoint_id
        )

        result.data[
            "checkpoint_revision"
        ] = (
            checkpoint
            .edit_revision
        )

        result.data[
            "checkpoint_path"
        ] = (
            checkpoint
            .snapshot
            .path
        )

        result.data[
            "checkpoint_existed_before"
        ] = (
            checkpoint
            .snapshot
            .existed
        )

        result.data[
            "checkpoint_before_sha256"
        ] = (
            checkpoint
            .snapshot
            .sha256
        )

        result.data[
            "checkpoint_sealed"
        ] = (
            checkpoint_sealed
        )

        # =====================================================
        # Sealed Safety State
        # =====================================================

        if (
            checkpoint_sealed
            and sealed
            is not None
        ):

            result.data[
                "checkpoint_after_sha256"
            ] = (
                sealed
                .after_sha256
            )

            result.data[
                "safety_degraded"
            ] = False

        else:

            result.data[
                "checkpoint_after_sha256"
            ] = None

            result.data[
                "safety_degraded"
            ] = True

            result.data[
                "checkpoint_failure_type"
            ] = (
                "checkpoint_seal"
            )

            result.data[
                "checkpoint_error"
            ] = (
                checkpoint_error
            )

            result.data[
                "checkpoint_warning"
            ] = (
                "The edit physically succeeded, "
                "but rollback protection for this "
                "edit could not be finalized."
            )

        # =====================================================
        # Stage 11 Agent-Owned Edit Tracking
        #
        # This must run even if checkpoint sealing failed,
        # because the file physically changed.
        # =====================================================

        if (
            self.on_successful_edit
            is not None
        ):

            try:

                self.on_successful_edit(
                    path
                )

            except Exception as e:

                result.data[
                    "git_tracking_warning"
                ] = (
                    f"{type(e).__name__}: "
                    f"{e}"
                )

        return execution

    # =========================================================
    # Failure Builder
    # =========================================================

    @staticmethod
    def _checkpoint_failure(
        *,
        prepared: PreparedToolCall,
        failure_type: str,
        summary: str,
        error: Exception,
        path: str | None = None,
    ) -> ToolExecution:

        data = {
            "tool_name": (
                prepared.tool_name
            ),
            "failure_type": (
                failure_type
            ),
        }

        if (
            path
            is not None
        ):

            data[
                "path"
            ] = path

        return ToolExecution(
            tool_name=(
                prepared.tool_name
            ),
            arguments=(
                prepared.arguments
            ),
            result=ToolResult(
                success=False,
                summary=summary,
                data=data,
                error=(
                    f"{type(error).__name__}: "
                    f"{error}"
                ),
            ),
        )
