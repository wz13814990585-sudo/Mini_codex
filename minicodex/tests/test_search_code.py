from ..tools.search_code import SearchCodeTool
from ..tools.base import ToolResult


def test_search_code_returns_structured_matches(
    tmp_path,
):
    file_path = tmp_path / "example.py"

    file_path.write_text(
        "def foo():\n"
        "    return 1\n"
        "\n"
        "foo()\n",
        encoding="utf-8",
    )

    tool = SearchCodeTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(
        query="foo"
    )

    assert isinstance(
        result,
        ToolResult,
    )

    assert result.success is True

    assert (
        result.data["returned_match_count"]
        == 2
    )

    assert result.data["truncated"] is False

    assert (
        result.data["matches"][0]["path"]
        == "example.py"
    )


def test_search_code_no_matches_is_success(
    tmp_path,
):
    file_path = tmp_path / "example.py"

    file_path.write_text(
        "x = 1\n",
        encoding="utf-8",
    )

    tool = SearchCodeTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(
        query="not_here"
    )

    assert result.success is True

    assert (
        result.data["returned_match_count"]
        == 0
    )

    assert result.data["matches"] == []

    assert result.data["truncated"] is False


def test_search_code_reports_truncation(
    tmp_path,
):
    file_path = tmp_path / "example.py"

    file_path.write_text(
        "foo\nfoo\nfoo\nfoo\n",
        encoding="utf-8",
    )

    tool = SearchCodeTool(
        workspace=str(tmp_path)
    )

    result = tool.execute(
        query="foo",
        max_results=2,
    )

    assert (
        result.data["returned_match_count"]
        == 2
    )

    assert result.data["truncated"] is True