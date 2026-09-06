from collections.abc import Callable

from .checkpoint import (
    CheckpointManager,
)
from .tool_executor import (
    PreparedToolCall,
    ToolExecution,
    ToolExecutor,
)

from ..tools.results import (
    ToolResult,
)


# =============================================================
# Protected Edit Tools
# =============================================================


CHECKPOINTED_EDIT_TOOLS = {
    "patch_file",
    "replace_lines",
    "replace_symbol",
    "write_file",
}


# =============================================================
# Checkpointing Executor
# =============================================================


class CheckpointingToolExecutor:
    """
    Safety wrapper around ToolExecutor.

    Edit execution:

        capture before-state
            ↓
        execute actual edit
            ↓
        failure → discard checkpoint
        success → seal after-state
    """

    def __init__(
        self,
        *,
        executor: ToolExecutor,
        checkpoint_manager: CheckpointManager,
        next_edit_revision: Callable[
            [],
            int,
        ],
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
        # Already Failed During Preparation
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
        # Non-Edit Tool
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
        # Explicit Target Path
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
        # Next Revision
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
        # Capture Before-State
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

        # =====================================================
        # Execute Real Edit
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
        # Failed Edit
        # =====================================================

        if not result.success:

            (
                self.checkpoint_manager
                .discard(
                    checkpoint
                    .checkpoint_id
                )
            )

            return execution

        # =====================================================
        # Seal After-State
        # =====================================================

        try:

            sealed = (
                self.checkpoint_manager
                .seal(
                    checkpoint
                    .checkpoint_id
                )
            )

        except Exception as e:

            # The edit physically succeeded, but its safety
            # checkpoint could not be finalized.
            #
            # Do NOT silently report edit success.
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
                        "The edit was written, but "
                        "checkpoint finalization failed."
                    ),
                    data={
                        "tool_name": (
                            prepared.tool_name
                        ),
                        "path": path,
                        "checkpoint_id": (
                            checkpoint
                            .checkpoint_id
                        ),
                        "failure_type": (
                            "checkpoint_seal"
                        ),
                    },
                    error=(
                        f"{type(e).__name__}: "
                        f"{e}"
                    ),
                ),
            )

        # =====================================================
        # Expose Checkpoint Metadata
        # =====================================================

        result.data[
            "checkpoint_id"
        ] = (
            sealed
            .checkpoint_id
        )

        result.data[
            "checkpoint_revision"
        ] = (
            sealed
            .edit_revision
        )

        result.data[
            "checkpoint_path"
        ] = (
            sealed
            .snapshot
            .path
        )

        result.data[
            "checkpoint_existed_before"
        ] = (
            sealed
            .snapshot
            .existed
        )

        result.data[
            "checkpoint_before_sha256"
        ] = (
            sealed
            .snapshot
            .sha256
        )

        result.data[
            "checkpoint_after_sha256"
        ] = (
            sealed
            .after_sha256
        )

        return execution

    # =========================================================
    # Internal Failure Builder
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