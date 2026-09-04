from ..tools.list_files import ListFilesTool    
from ..tools.results import ToolResult

def test_list_files_returns_structured_entries(
    tmp_path,
):
    (tmp_path / "agent").mkdir()

    (tmp_path / "main.py").write_text(
        "print('hello')\n",
        encoding="utf-8",
    )

    tool = ListFilesTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(".")

    assert result.success is True

    assert result.data["entry_count"] == 2
    assert result.data["file_count"] == 1
    assert result.data["directory_count"] == 1

    assert {
        "path": "agent",
        "type": "directory",
    } in result.data["entries"]

    assert {
        "path": "main.py",
        "type": "file",
    } in result.data["entries"]

def test_list_empty_directory_is_success(
    tmp_path,
):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    tool = ListFilesTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(
        path="empty"
    )

    assert result.success is True
    assert result.data["entry_count"] == 0
    assert result.data["entries"] == []