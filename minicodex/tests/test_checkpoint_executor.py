import json
from pathlib import Path

from ..agent.editing import (
    CheckpointManager,
)
from ..agent.editing import (
    CheckpointingToolExecutor,
)
from ..agent.runtime import (
    ToolExecutor,
)
from ..tools.base import (
    BaseTool,
)
from ..tools.registry import (
    ToolRegistry,
)
from ..tools.results import (
    ToolResult,
)


# =============================================================
# Fake Read Tool
# =============================================================


class FakeReadTool(
    BaseTool
):

    name = "read_file"

    description = (
        "Fake read tool."
    )

    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def execute(
        self,
    ) -> ToolResult:

        return ToolResult(
            success=True,
            summary=(
                "Read completed."
            ),
            data={},
        )


# =============================================================
# Fake Write Tool
# =============================================================


class FakeWriteTool(
    BaseTool
):

    name = "write_file"

    description = (
        "Fake write tool."
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
            },
            "content": {
                "type": "string",
            },
            "fail": {
                "type": "boolean",
            },
        },
        "required": [
            "path",
            "content",
        ],
    }

    def __init__(
        self,
        workspace: Path,
    ):

        self.workspace = (
            Path(
                workspace
            )
            .resolve()
        )

        self.execution_count = 0

    def execute(
        self,
        path: str,
        content: str,
        fail: bool = False,
    ) -> ToolResult:

        self.execution_count += 1

        if fail:

            return ToolResult(
                success=False,
                summary=(
                    "Fake edit failed."
                ),
                data={
                    "path": path,
                },
                error=(
                    "simulated failure"
                ),
            )

        file_path = (
            self.workspace
            / path
        )

        file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        file_path.write_text(
            content,
            encoding="utf-8",
        )

        return ToolResult(
            success=True,
            summary=(
                "Fake edit succeeded."
            ),
            data={
                "path": path,
            },
        )


# =============================================================
# Build Executor
# =============================================================


def build_executor(
    tmp_path: Path,
    revision: int = 1,
    on_successful_edit=None,
):

    registry = (
        ToolRegistry()
    )

    read_tool = (
        FakeReadTool()
    )

    write_tool = (
        FakeWriteTool(
            workspace=tmp_path
        )
    )

    registry.register(
        read_tool
    )

    registry.register(
        write_tool
    )

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    base_executor = (
        ToolExecutor(
            registry
        )
    )

    executor = (
        CheckpointingToolExecutor(
            executor=(
                base_executor
            ),
            checkpoint_manager=(
                manager
            ),
            next_edit_revision=(
                lambda: revision
            ),
            on_successful_edit=(
                on_successful_edit
            ),
        )
    )

    return (
        executor,
        manager,
        write_tool,
    )


# =============================================================
# Successful Existing File
# =============================================================


def test_successful_edit_captures_before_state(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.txt"
    )

    file_path.write_text(
        "before",
        encoding="utf-8",
    )

    (
        executor,
        manager,
        _,
    ) = (
        build_executor(
            tmp_path,
            revision=1,
        )
    )

    prepared = (
        executor.prepare(
            tool_name="write_file",
            raw_arguments=(
                json.dumps(
                    {
                        "path": "demo.txt",
                        "content": "after",
                    }
                )
            ),
        )
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    assert (
        execution.result.success
        is True
    )

    assert (
        file_path.read_text(
            encoding="utf-8"
        )
        == "after"
    )

    checkpoint = (
        manager.latest()
    )

    assert (
        checkpoint
        is not None
    )

    assert (
        checkpoint.edit_revision
        == 1
    )

    assert (
        checkpoint.snapshot.content
        == "before"
    )

    assert (
        execution.result.data[
            "checkpoint_id"
        ]
        == checkpoint.checkpoint_id
    )

    assert (
        execution.result.data[
            "checkpoint_sealed"
        ]
        is True
    )

    assert (
        execution.result.data[
            "safety_degraded"
        ]
        is False
    )


# =============================================================
# New File
# =============================================================


def test_new_file_edit_captures_missing_state(
    tmp_path: Path,
):

    (
        executor,
        manager,
        _,
    ) = (
        build_executor(
            tmp_path,
            revision=1,
        )
    )

    prepared = (
        executor.prepare(
            tool_name="write_file",
            raw_arguments=(
                json.dumps(
                    {
                        "path": (
                            "new_file.txt"
                        ),
                        "content": (
                            "created"
                        ),
                    }
                )
            ),
        )
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    assert (
        execution.result.success
        is True
    )

    checkpoint = (
        manager.latest()
    )

    assert (
        checkpoint
        is not None
    )

    assert (
        checkpoint.snapshot.existed
        is False
    )

    assert (
        checkpoint.snapshot.content
        is None
    )


# =============================================================
# Failed Edit
# =============================================================


def test_failed_edit_discards_checkpoint(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.txt"
    )

    file_path.write_text(
        "before",
        encoding="utf-8",
    )

    (
        executor,
        manager,
        _,
    ) = (
        build_executor(
            tmp_path,
            revision=1,
        )
    )

    prepared = (
        executor.prepare(
            tool_name="write_file",
            raw_arguments=(
                json.dumps(
                    {
                        "path": "demo.txt",
                        "content": "after",
                        "fail": True,
                    }
                )
            ),
        )
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    assert (
        execution.result.success
        is False
    )

    assert (
        manager.latest()
        is None
    )

    assert (
        file_path.read_text(
            encoding="utf-8"
        )
        == "before"
    )


# =============================================================
# Missing Path
# =============================================================


def test_edit_without_path_is_blocked(
    tmp_path: Path,
):

    (
        executor,
        manager,
        write_tool,
    ) = (
        build_executor(
            tmp_path,
            revision=1,
        )
    )

    prepared = (
        executor.prepare(
            tool_name="write_file",
            raw_arguments=(
                json.dumps(
                    {
                        "content": "hello",
                    }
                )
            ),
        )
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    assert (
        execution.result.success
        is False
    )

    assert (
        execution.result.data[
            "failure_type"
        ]
        == "checkpoint_precondition"
    )

    assert (
        manager.latest()
        is None
    )

    assert (
        write_tool.execution_count
        == 0
    )


# =============================================================
# Non Edit
# =============================================================


def test_non_edit_tool_does_not_checkpoint(
    tmp_path: Path,
):

    (
        executor,
        manager,
        _,
    ) = (
        build_executor(
            tmp_path,
            revision=1,
        )
    )

    prepared = (
        executor.prepare(
            tool_name="read_file",
            raw_arguments="{}",
        )
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    assert (
        execution.result.success
        is True
    )

    assert (
        manager.latest()
        is None
    )


# =============================================================
# Revision Binding
# =============================================================


def test_checkpoint_is_bound_to_next_revision(
    tmp_path: Path,
):

    current_revision = 7

    registry = (
        ToolRegistry()
    )

    write_tool = (
        FakeWriteTool(
            workspace=tmp_path
        )
    )

    registry.register(
        write_tool
    )

    manager = (
        CheckpointManager(
            workspace=tmp_path
        )
    )

    executor = (
        CheckpointingToolExecutor(
            executor=(
                ToolExecutor(
                    registry
                )
            ),
            checkpoint_manager=(
                manager
            ),
            next_edit_revision=(
                lambda: (
                    current_revision
                    + 1
                )
            ),
        )
    )

    prepared = (
        executor.prepare(
            tool_name="write_file",
            raw_arguments=(
                json.dumps(
                    {
                        "path": "demo.txt",
                        "content": "new",
                    }
                )
            ),
        )
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    assert (
        execution.result.success
        is True
    )

    checkpoint = (
        manager.latest()
    )

    assert (
        checkpoint
        is not None
    )

    assert (
        checkpoint.edit_revision
        == 8
    )

    assert (
        execution.result.data[
            "checkpoint_revision"
        ]
        == 8
    )

    assert (
        checkpoint.sealed
        is True
    )

    assert (
        checkpoint.after_sha256
        is not None
    )


# =============================================================
# Seal
# =============================================================


def test_successful_edit_seals_checkpoint(
    tmp_path: Path,
):

    (
        executor,
        manager,
        _,
    ) = (
        build_executor(
            tmp_path,
            revision=1,
        )
    )

    prepared = (
        executor.prepare(
            tool_name="write_file",
            raw_arguments=(
                json.dumps(
                    {
                        "path": "demo.txt",
                        "content": "after",
                    }
                )
            ),
        )
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    assert (
        execution.result.success
        is True
    )

    checkpoint = (
        manager.latest()
    )

    assert (
        checkpoint
        is not None
    )

    assert (
        checkpoint.sealed
        is True
    )

    assert (
        checkpoint.after_sha256
        is not None
    )

    assert (
        execution.result.data[
            "checkpoint_after_sha256"
        ]
        == checkpoint.after_sha256
    )


# =============================================================
# Successful Edit Callback
# =============================================================


def test_successful_edit_calls_tracking_callback(
    tmp_path: Path,
):

    touched = []

    (
        executor,
        _,
        _,
    ) = (
        build_executor(
            tmp_path,
            revision=1,
            on_successful_edit=(
                touched.append
            ),
        )
    )

    prepared = (
        executor.prepare(
            tool_name="write_file",
            raw_arguments=(
                json.dumps(
                    {
                        "path": "demo.txt",
                        "content": "hello",
                    }
                )
            ),
        )
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    assert (
        execution.result.success
        is True
    )

    assert (
        touched
        == [
            "demo.txt"
        ]
    )


# =============================================================
# Seal Failure Does NOT Lie About Physical Edit
# =============================================================


def test_seal_failure_keeps_physical_edit_successful(
    tmp_path: Path,
):

    touched = []

    (
        executor,
        manager,
        _,
    ) = (
        build_executor(
            tmp_path,
            revision=3,
            on_successful_edit=(
                touched.append
            ),
        )
    )

    def broken_seal(
        checkpoint_id,
    ):

        raise RuntimeError(
            "simulated seal failure"
        )

    manager.seal = (
        broken_seal
    )

    prepared = (
        executor.prepare(
            tool_name="write_file",
            raw_arguments=(
                json.dumps(
                    {
                        "path": "demo.txt",
                        "content": "physical change",
                    }
                )
            ),
        )
    )

    execution = (
        executor.execute_prepared(
            prepared
        )
    )

    # The file really changed, therefore success must remain true.
    assert (
        execution.result.success
        is True
    )

    assert (
        (
            tmp_path
            / "demo.txt"
        ).read_text(
            encoding="utf-8"
        )
        == "physical change"
    )

    assert (
        execution.result.data[
            "checkpoint_sealed"
        ]
        is False
    )

    assert (
        execution.result.data[
            "safety_degraded"
        ]
        is True
    )

    assert (
        execution.result.data[
            "checkpoint_failure_type"
        ]
        == "checkpoint_seal"
    )

    # Invalid checkpoint was discarded.
    assert (
        manager.latest()
        is None
    )

    # Git ownership tracking still occurs because the file
    # physically changed.
    assert (
        touched
        == [
            "demo.txt"
        ]
    )