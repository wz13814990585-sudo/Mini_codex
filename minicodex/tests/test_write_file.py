from ..tools.write_file import WriteFileTool
from ..tools.base import ToolResult

def test_write_file_reports_created(
    tmp_path,
):
    tool = WriteFileTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(
        path="example.py",
        content="x = 1\n",
    )

    assert result.success is True
    assert result.data["created"] is True
    assert result.data["overwritten"] is False
    assert result.data["chars_written"] == 6


def test_write_file_reports_overwritten(
    tmp_path,
):
    file_path = tmp_path / "example.py"

    file_path.write_text(
        "x = 1\n",
        encoding="utf-8",
    )

    tool = WriteFileTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(
        path="example.py",
        content="x = 2\n",
    )

    assert result.success is True
    assert result.data["created"] is False
    assert result.data["overwritten"] is True