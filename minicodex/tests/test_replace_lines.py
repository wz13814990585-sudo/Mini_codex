from pathlib import Path

import pytest

from ..tools.replace_lines import (
    ReplaceLinesTool,
)


def test_replace_lines_basic(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    file_path.write_text(
        """
def first():
    return 1

def second():
    return 2
""".strip()
        + "\n"
    )

    tool = ReplaceLinesTool(
        workspace=tmp_path
    )

    result = tool.execute(
        path="demo.py",
        start_line=4,
        end_line=5,
        new_text=(
            "def second():\n"
            "    return 20"
        ),
    )

    assert (
        result.success
        is True
    )

    updated = (
        file_path.read_text()
    )

    assert (
        "return 20"
        in updated
    )

    # Prefer an exact-line check: "return 2" is also a
    # substring of "return 20", so a raw `in` assertion
    # would false-fail after a successful replacement.
    assert "    return 2\n" not in updated
    assert updated.splitlines() == [
        "def first():",
        "    return 1",
        "",
        "def second():",
        "    return 20",
    ]


def test_replace_lines_expected_text_guard(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    file_path.write_text(
        (
            "def run():\n"
            "    return 1\n"
        )
    )

    tool = ReplaceLinesTool(
        workspace=tmp_path
    )

    result = tool.execute(
        path="demo.py",
        start_line=1,
        end_line=2,
        expected_text=(
            "def run():\n"
            "    return 1"
        ),
        new_text=(
            "def run():\n"
            "    return 2"
        ),
    )

    assert (
        result.success
        is True
    )

    assert (
        file_path.read_text()
        == (
            "def run():\n"
            "    return 2\n"
        )
    )


def test_replace_lines_rejects_stale_expected_text(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    file_path.write_text(
        (
            "def run():\n"
            "    return 99\n"
        )
    )

    tool = ReplaceLinesTool(
        workspace=tmp_path
    )

    with pytest.raises(
        ValueError,
        match="no longer matches",
    ):

        tool.execute(
            path="demo.py",
            start_line=1,
            end_line=2,
            expected_text=(
                "def run():\n"
                "    return 1"
            ),
            new_text=(
                "def run():\n"
                "    return 2"
            ),
        )


def test_replace_lines_rejects_invalid_range(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    file_path.write_text(
        "a\nb\nc\n"
    )

    tool = ReplaceLinesTool(
        workspace=tmp_path
    )

    with pytest.raises(
        ValueError,
        match="end_line",
    ):

        tool.execute(
            path="demo.py",
            start_line=3,
            end_line=2,
            new_text="x",
        )


def test_replace_lines_rejects_range_past_eof(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    file_path.write_text(
        "a\nb\n"
    )

    tool = ReplaceLinesTool(
        workspace=tmp_path
    )

    with pytest.raises(
        ValueError,
        match="exceeds",
    ):

        tool.execute(
            path="demo.py",
            start_line=1,
            end_line=5,
            new_text="x",
        )


def test_replace_lines_preserves_final_newline(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    file_path.write_text(
        "a\nb\nc\n"
    )

    tool = ReplaceLinesTool(
        workspace=tmp_path
    )

    tool.execute(
        path="demo.py",
        start_line=2,
        end_line=2,
        new_text="B",
    )

    content = (
        file_path.read_text()
    )

    assert (
        content
        == "a\nB\nc\n"
    )