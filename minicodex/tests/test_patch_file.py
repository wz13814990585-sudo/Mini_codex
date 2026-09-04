from ..tools.patch_file import PatchFileTool
from ..tools.results import ToolResult


def test_patch_file_returns_structured_result(
    tmp_path,
) -> None:
    file_path = tmp_path / "example.py"
    file_path.write_text(
        "x = 1\n",
        encoding="utf-8",
    )

    tool = PatchFileTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(
        path="example.py",
        old_text="x = 1",
        new_text="x = 2",
    )

    assert isinstance(
        result,
        ToolResult,
    )

    assert result.success is True

    assert (
        result.data["path"]
        == "example.py"
    )

    assert (
        result.data["replacement_count"]
        == 1
    )

    assert (
        "Successfully patched"
        in result.summary
    )

    assert (
        file_path.read_text(
            encoding="utf-8"
        )
        == "x = 2\n"
    )
