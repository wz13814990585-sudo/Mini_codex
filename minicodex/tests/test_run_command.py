from ..tools.run_command import RunCommandTool
from ..tools.results import ToolResult

def test_run_command_success(
    tmp_path,
):
    tool = RunCommandTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(
        "python -c \"print('hello')\""
    )

    assert result.success is True
    assert result.data["exit_code"] == 0
    assert result.data["command_succeeded"] is True
    assert "hello" in result.data["stdout"]

def test_run_command_nonzero_exit_is_not_tool_failure(
    tmp_path,
):
    tool = RunCommandTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(
        "python -c \"raise SystemExit(2)\""
    )

    assert result.success is True
    assert result.data["exit_code"] == 2
    assert result.data["command_succeeded"] is False

def test_run_command_timeout_is_tool_failure(
    tmp_path,
):
    tool = RunCommandTool(
        workspace=str(tmp_path),
        timeout=1,
    )

    result = tool.execute(
        "sleep 2"
    )

    assert result.success is False
    assert result.data["timed_out"] is True