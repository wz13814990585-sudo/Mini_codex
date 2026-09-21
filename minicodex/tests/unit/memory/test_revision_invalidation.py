from ....agent.memory import WorkingMemory
from ....tools.results import ToolResult


def test_edit_invalidates_old_path_observation_and_records_new_revision():
    memory = WorkingMemory()
    memory.record_tool_result(
        tool_name="read_file",
        arguments={"path": "app.py"},
        result=ToolResult(success=True, summary="read", data={}),
        revision=2,
    )
    assert memory.get("file:app.py:observation").revision == 2

    memory.record_tool_result(
        tool_name="patch_file",
        arguments={"path": "app.py"},
        result=ToolResult(success=True, summary="edited", data={}),
        revision=3,
    )

    assert memory.get("file:app.py:observation") is None
    assert memory.get("file:app.py:edit").revision == 3
