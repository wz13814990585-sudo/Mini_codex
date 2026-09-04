from ..tools.read_file import ReadFileTool
from ..tools.results import ToolResult

def test_read_file_returns_structured_result(
    tmp_path,
):
    file_path = tmp_path / "example.py"

    file_path.write_text(
        "a\nb\nc\nd\n",
        encoding="utf-8",
    )

    tool = ReadFileTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(
        path="example.py",
        offset=2,
        limit=2,
    )

    assert isinstance(
        result,
        ToolResult,
    )

    assert result.success is True

    assert result.data["start_line"] == 2
    assert result.data["end_line"] == 3
    assert result.data["total_lines"] == 4

    assert result.data["has_more"] is True
    assert result.data["next_offset"] == 4

    assert result.llm_content == "b\nc"


def test_read_empty_file_is_not_failure(
    tmp_path,
):
    file_path = tmp_path / "empty.py"

    file_path.write_text(
        "",
        encoding="utf-8",
    )

    tool = ReadFileTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(
        path="empty.py"
    )

    assert result.success is True

    assert result.data["total_lines"] == 0

    assert result.llm_content == ""