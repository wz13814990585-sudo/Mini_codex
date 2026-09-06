from ..agent.working_memory import (
    MemoryKind,
    WorkingMemory,
)
from ..agent.working_summary import (
    WorkingSummary,
)
from ..tools.results import (
    ToolResult,
)


# =============================================================
# Upsert
# =============================================================


def test_working_memory_upsert_replaces_old_state():

    memory = (
        WorkingMemory()
    )

    memory.upsert(
        key="state:a",
        kind=(
            MemoryKind.GENERAL
        ),
        value="old",
    )

    memory.upsert(
        key="state:a",
        kind=(
            MemoryKind.GENERAL
        ),
        value="new",
    )

    assert (
        len(
            memory
        )
        == 1
    )

    assert (
        memory.get(
            "state:a"
        ).value
        == "new"
    )


# =============================================================
# Bounded
# =============================================================


def test_working_memory_is_bounded():

    memory = (
        WorkingMemory(
            max_entries=3
        )
    )

    for index in range(
        5
    ):

        memory.upsert(
            key=(
                f"item:{index}"
            ),
            kind=(
                MemoryKind.GENERAL
            ),
            value=(
                f"value {index}"
            ),
        )

    assert (
        len(
            memory
        )
        == 3
    )

    assert (
        memory.get(
            "item:0"
        )
        is None
    )

    assert (
        memory.get(
            "item:4"
        )
        is not None
    )


# =============================================================
# Read Observation
# =============================================================


def test_read_file_creates_structured_memory():

    memory = (
        WorkingMemory()
    )

    memory.record_tool_result(
        tool_name="read_file",
        arguments={
            "path": (
                "app.py"
            ),
        },
        result=ToolResult(
            success=True,
            summary="Read.",
            data={
                "path": (
                    "app.py"
                ),
                "start_line": 1,
                "end_line": 20,
                "total_lines": 100,
                "has_more": True,
            },
        ),
    )

    entry = (
        memory.get(
            (
                "file:"
                "app.py:"
                "observation"
            )
        )
    )

    assert (
        entry
        is not None
    )

    assert (
        entry.kind
        == MemoryKind.FILE
    )

    assert (
        entry.path
        == "app.py"
    )

    assert (
        "1-20"
        in entry.value
    )

    assert (
        "More lines remain unread"
        in entry.value
    )


# =============================================================
# Edit Invalidates Stale Read
# =============================================================


def test_edit_invalidates_old_file_observation():

    memory = (
        WorkingMemory()
    )

    memory.record_tool_result(
        tool_name="read_file",
        arguments={
            "path": (
                "app.py"
            ),
        },
        result=ToolResult(
            success=True,
            summary="Read.",
            data={
                "path": (
                    "app.py"
                ),
                "start_line": 1,
                "end_line": 10,
                "total_lines": 10,
                "has_more": False,
            },
        ),
    )

    assert (
        memory.get(
            (
                "file:"
                "app.py:"
                "observation"
            )
        )
        is not None
    )

    memory.record_tool_result(
        tool_name="replace_symbol",
        arguments={
            "path": (
                "app.py"
            ),
        },
        result=ToolResult(
            success=True,
            summary="Edited.",
            data={
                "path": (
                    "app.py"
                ),
                "checkpoint_id": (
                    "cp-1"
                ),
                "checkpoint_revision": (
                    3
                ),
                "checkpoint_sealed": (
                    True
                ),
                "safety_degraded": (
                    False
                ),
            },
        ),
    )

    # Previous read knowledge is stale.
    assert (
        memory.get(
            (
                "file:"
                "app.py:"
                "observation"
            )
        )
        is None
    )

    edit_entry = (
        memory.get(
            (
                "file:"
                "app.py:"
                "edit"
            )
        )
    )

    assert (
        edit_entry
        is not None
    )

    assert (
        edit_entry.revision
        == 3
    )


# =============================================================
# Latest Validation Replaces Old Validation
# =============================================================


def test_validation_memory_keeps_latest_state():

    memory = (
        WorkingMemory()
    )

    arguments = {
        "path": (
            "tests/test_app.py"
        ),
        "purpose": (
            "acceptance"
        ),
    }

    memory.record_tool_result(
        tool_name="run_tests",
        arguments=arguments,
        result=ToolResult(
            success=True,
            summary="Failed.",
            data={
                "path": (
                    "tests/test_app.py"
                ),
                "purpose": (
                    "acceptance"
                ),
                "tests_passed": (
                    False
                ),
                "passed": 2,
                "failed": 1,
                "errors": 0,
            },
        ),
    )

    memory.record_tool_result(
        tool_name="run_tests",
        arguments=arguments,
        result=ToolResult(
            success=True,
            summary="Passed.",
            data={
                "path": (
                    "tests/test_app.py"
                ),
                "purpose": (
                    "acceptance"
                ),
                "tests_passed": (
                    True
                ),
                "passed": 3,
                "failed": 0,
                "errors": 0,
            },
        ),
    )

    key = (
        "validation:"
        "acceptance:"
        "tests/test_app.py"
    )

    entry = (
        memory.get(
            key
        )
    )

    assert (
        entry
        is not None
    )

    assert (
        len(
            [
                item
                for item
                in memory.entries
                if item
                == key
            ]
        )
        == 1
    )

    assert (
        "passed;"
        in entry.value
    )

    assert (
        "0 failed"
        in entry.value
    )


# =============================================================
# Different Validation Series Stay Separate
# =============================================================


def test_acceptance_and_regression_memory_are_separate():

    memory = (
        WorkingMemory()
    )

    memory.record_tool_result(
        tool_name="run_tests",
        arguments={
            "path": (
                "tests/test_app.py"
            ),
            "purpose": (
                "acceptance"
            ),
        },
        result=ToolResult(
            success=True,
            summary="Passed.",
            data={
                "tests_passed": (
                    True
                ),
                "passed": 1,
                "failed": 0,
                "errors": 0,
            },
        ),
    )

    memory.record_tool_result(
        tool_name="run_tests",
        arguments={
            "path": ".",
            "purpose": (
                "regression"
            ),
        },
        result=ToolResult(
            success=True,
            summary="Passed.",
            data={
                "tests_passed": (
                    True
                ),
                "passed": 100,
                "failed": 0,
                "errors": 0,
            },
        ),
    )

    assert (
        memory.get(
            (
                "validation:"
                "acceptance:"
                "tests/test_app.py"
            )
        )
        is not None
    )

    assert (
        memory.get(
            (
                "validation:"
                "regression:."
            )
        )
        is not None
    )


# =============================================================
# Safety Caution
# =============================================================


def test_safety_caution_is_remembered():

    memory = (
        WorkingMemory()
    )

    memory.record_tool_result(
        tool_name="replace_lines",
        arguments={
            "path": (
                "config.py"
            ),
        },
        result=ToolResult(
            success=True,
            summary="Edited.",
            data={
                "path": (
                    "config.py"
                ),
                "checkpoint_revision": 2,
                "checkpoint_sealed": True,
                "safety": {
                    "level": (
                        "caution"
                    ),
                    "allowed": (
                        True
                    ),
                    "rule": (
                        "preexisting_user_change"
                    ),
                    "reason": (
                        "File was already dirty."
                    ),
                },
            },
        ),
    )

    safety_entries = [
        entry
        for entry
        in memory.entries.values()
        if (
            entry.kind
            == MemoryKind.SAFETY
        )
    ]

    assert (
        len(
            safety_entries
        )
        == 1
    )

    assert (
        "preexisting_user_change"
        in (
            safety_entries[
                0
            ].value
        )
    )


# =============================================================
# Failure Memory
# =============================================================


def test_failure_is_remembered():

    memory = (
        WorkingMemory()
    )

    memory.record_tool_result(
        tool_name="read_file",
        arguments={
            "path": (
                "missing.py"
            ),
        },
        result=ToolResult(
            success=False,
            summary="Failed.",
            data={
                "failure_type": (
                    "execution"
                ),
            },
            error=(
                "File not found"
            ),
        ),
    )

    failures = [
        entry
        for entry
        in memory.entries.values()
        if (
            entry.kind
            == MemoryKind.FAILURE
        )
    ]

    assert (
        len(
            failures
        )
        == 1
    )

    assert (
        "File not found"
        in failures[
            0
        ].value
    )


# =============================================================
# Reset
# =============================================================


def test_working_memory_reset():

    memory = (
        WorkingMemory()
    )

    memory.upsert(
        key="x",
        kind=(
            MemoryKind.GENERAL
        ),
        value="value",
    )

    assert (
        len(
            memory
        )
        == 1
    )

    memory.reset()

    assert (
        len(
            memory
        )
        == 0
    )


# =============================================================
# Summary Integration
# =============================================================


def test_working_summary_updates_working_memory():

    summary = (
        WorkingSummary()
    )

    summary.record_tool_result(
        tool_name="read_file",
        arguments={
            "path": (
                "agent.py"
            ),
        },
        result=ToolResult(
            success=True,
            summary="Read.",
            data={
                "path": (
                    "agent.py"
                ),
                "start_line": 1,
                "end_line": 20,
                "total_lines": 40,
                "has_more": True,
            },
        ),
    )

    assert (
        summary.memory.get(
            (
                "file:"
                "agent.py:"
                "observation"
            )
        )
        is not None
    )

    rendered = (
        summary.render()
    )

    assert (
        "Structured working memory"
        in rendered
    )

    assert (
        "agent.py"
        in rendered
    )

    assert (
        "Recent execution facts"
        in rendered
    )


# =============================================================
# Summary Reset Also Resets Memory
# =============================================================


def test_summary_reset_resets_working_memory():

    summary = (
        WorkingSummary()
    )

    summary.record_tool_result(
        tool_name="read_file",
        arguments={
            "path": (
                "app.py"
            ),
        },
        result=ToolResult(
            success=True,
            summary="Read.",
            data={
                "path": (
                    "app.py"
                ),
            },
        ),
    )

    assert (
        len(
            summary.memory
        )
        > 0
    )

    summary.reset()

    assert (
        summary.items
        == []
    )

    assert (
        len(
            summary.memory
        )
        == 0
    )