from ..tools.write_file import WriteFileTool
from ..tools.results import ToolResult

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

from pathlib import Path

import pytest

from ..tools.write_file import (
    WriteFileTool,
)


def test_write_file_verifies_created_file(
    tmp_path: Path,
):

    tool = WriteFileTool(
        workspace=tmp_path
    )

    result = tool.execute(
        path="demo.py",
        content=(
            "def run():\n"
            "    return 1\n"
        ),
    )

    assert (
        result.success
        is True
    )

    assert (
        result.data[
            "changed"
        ]
        is True
    )

    assert (
        result.data[
            "content_verified"
        ]
        is True
    )

    assert (
        result.data[
            "syntax_validated"
        ]
        is True
    )


def test_write_file_rejects_noop_overwrite(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    content = (
        "def run():\n"
        "    return 1\n"
    )

    file_path.write_text(
        content
    )

    tool = WriteFileTool(
        workspace=tmp_path
    )

    with pytest.raises(
        ValueError,
        match="would not change",
    ):

        tool.execute(
            path="demo.py",
            content=content,
        )


def test_write_file_rejects_invalid_python_before_write(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    original = (
        "def run():\n"
        "    return 1\n"
    )

    file_path.write_text(
        original
    )

    tool = WriteFileTool(
        workspace=tmp_path
    )

    with pytest.raises(
        ValueError,
        match="invalid Python syntax",
    ):

        tool.execute(
            path="demo.py",
            content=(
                "def run()\n"
                "    return 2\n"
            ),
        )

    assert (
        file_path.read_text()
        == original
    )