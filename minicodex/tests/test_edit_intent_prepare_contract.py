"""P0.5-A2: edit_intent is internal tool-call metadata, not a backend arg."""

from __future__ import annotations

import json

from minicodex.agent.runtime.tool_executor import ToolExecutor
from minicodex.tools.editing.patch_file import PatchFileTool
from minicodex.tools.editing.write_file import WriteFileTool
from minicodex.tools.registry import ToolRegistry


def _executor_with_edit_tools() -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    registry.register(PatchFileTool())
    return ToolExecutor(registry)


def test_prepare_accepts_edit_intent_on_write_file():
    executor = _executor_with_edit_tools()
    prepared = executor.prepare(
        "write_file",
        json.dumps(
            {
                "path": "a.py",
                "content": "x = 1\n",
                "edit_intent": {"path": "a.py", "expected_text": "x = 1\n"},
            }
        ),
    )
    assert prepared.error is None
    assert prepared.arguments["path"] == "a.py"
    assert "edit_intent" in prepared.arguments


def test_prepare_accepts_edit_intent_on_patch_file():
    executor = _executor_with_edit_tools()
    prepared = executor.prepare(
        "patch_file",
        json.dumps(
            {
                "path": "a.py",
                "old_text": "x = 1",
                "new_text": "x = 2",
                "edit_intent": {"path": "a.py", "expected_text": "x = 2\n"},
            }
        ),
    )
    assert prepared.error is None
    assert "edit_intent" in prepared.arguments


def test_prepare_still_rejects_unknown_bogus_arg():
    executor = _executor_with_edit_tools()
    prepared = executor.prepare(
        "write_file",
        json.dumps({"path": "a.py", "content": "x = 1\n", "bogus_arg": True}),
    )
    assert prepared.error is not None
    assert prepared.error.data.get("failure_type") == "schema_validation"
    assert "bogus_arg" in (prepared.error.error or "")


def test_execute_strips_edit_intent_before_backend_tool():
    """Orchestration strips edit_intent; prepare may retain it for callers."""

    seen = {}

    class RecordingWrite(WriteFileTool):
        def execute(self, **kwargs):
            seen.update(kwargs)
            return super().execute(**kwargs)

    registry = ToolRegistry()
    registry.register(RecordingWrite())
    executor = ToolExecutor(registry)
    prepared = executor.prepare(
        "write_file",
        json.dumps(
            {
                "path": "a.py",
                "content": "x = 1\n",
                "edit_intent": {"path": "a.py", "expected_text": "x = 1\n"},
            }
        ),
    )
    assert prepared.error is None
    # Simulate tool_call_runner strip before execute_prepared.
    stripped = {
        k: v
        for k, v in prepared.arguments.items()
        if k not in {"validation_check", "edit_intent"}
    }
    from minicodex.agent.runtime.tool_types import PreparedToolCall

    execution = executor.execute_prepared(PreparedToolCall("write_file", stripped))
    assert "edit_intent" not in seen
    assert seen.get("path") == "a.py"
