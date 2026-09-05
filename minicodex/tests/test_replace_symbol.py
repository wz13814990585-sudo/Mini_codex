from pathlib import Path

import pytest

from ..agent.symbol_index import (
    SymbolIndex,
)
from ..tools.replace_symbol import (
    ReplaceSymbolTool,
)


def test_replace_top_level_function(
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

    index = SymbolIndex(
        workspace=tmp_path
    )

    tool = ReplaceSymbolTool(
        workspace=tmp_path,
        symbol_index=index,
    )

    result = tool.execute(
        symbol="run",
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
        result.data[
            "syntax_validated"
        ]
        is True
    )

    assert (
        file_path.read_text()
        == (
            "def run():\n"
            "    return 2\n"
        )
    )


def test_replace_method_preserves_indentation(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "agent.py"
    )

    file_path.write_text(
        (
            "class Agent:\n"
            "\n"
            "    def run(self):\n"
            "        return 1\n"
        )
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    tool = ReplaceSymbolTool(
        workspace=tmp_path,
        symbol_index=index,
    )

    tool.execute(
        symbol="Agent.run",
        new_text=(
            "def run(self):\n"
            "    return 2"
        ),
    )

    updated = (
        file_path.read_text()
    )

    assert (
        "    def run(self):"
        in updated
    )

    assert (
        "        return 2"
        in updated
    )


def test_replace_symbol_rejects_invalid_python(
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

    index = SymbolIndex(
        workspace=tmp_path
    )

    tool = ReplaceSymbolTool(
        workspace=tmp_path,
        symbol_index=index,
    )

    with pytest.raises(
        ValueError,
        match="invalid Python syntax",
    ):

        tool.execute(
            symbol="run",
            new_text=(
                "def run()\n"
                "    return 2"
            ),
        )

    # Invalid replacement must NOT damage the file.
    assert (
        file_path.read_text()
        == original
    )


def test_replace_symbol_rejects_missing_symbol(
    tmp_path: Path,
):

    (
        tmp_path
        / "demo.py"
    ).write_text(
        (
            "def hello():\n"
            "    pass\n"
        )
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    tool = ReplaceSymbolTool(
        workspace=tmp_path,
        symbol_index=index,
    )

    with pytest.raises(
        ValueError,
        match="was not found",
    ):

        tool.execute(
            symbol="missing",
            new_text=(
                "def missing():\n"
                "    pass"
            ),
        )


def test_replace_symbol_rejects_ambiguous_short_name(
    tmp_path: Path,
):

    (
        tmp_path
        / "first.py"
    ).write_text(
        (
            "class First:\n"
            "    def run(self):\n"
            "        return 1\n"
        )
    )

    (
        tmp_path
        / "second.py"
    ).write_text(
        (
            "class Second:\n"
            "    def run(self):\n"
            "        return 2\n"
        )
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    tool = ReplaceSymbolTool(
        workspace=tmp_path,
        symbol_index=index,
    )

    with pytest.raises(
        ValueError,
        match="ambiguous",
    ):

        tool.execute(
            symbol="run",
            new_text=(
                "def run(self):\n"
                "    return 3"
            ),
        )


def test_replace_symbol_path_disambiguates(
    tmp_path: Path,
):

    (
        tmp_path
        / "first.py"
    ).write_text(
        (
            "class First:\n"
            "    def run(self):\n"
            "        return 1\n"
        )
    )

    second_file = (
        tmp_path
        / "second.py"
    )

    second_file.write_text(
        (
            "class Second:\n"
            "    def run(self):\n"
            "        return 2\n"
        )
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    tool = ReplaceSymbolTool(
        workspace=tmp_path,
        symbol_index=index,
    )

    result = tool.execute(
        symbol="run",
        path="second.py",
        new_text=(
            "def run(self):\n"
            "    return 20"
        ),
    )

    assert (
        result.success
        is True
    )

    assert (
        "return 20"
        in second_file.read_text()
    )


def test_replace_symbol_expected_text_guard(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    file_path.write_text(
        (
            "def run():\n"
            "    return 10\n"
        )
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    tool = ReplaceSymbolTool(
        workspace=tmp_path,
        symbol_index=index,
    )

    with pytest.raises(
        ValueError,
        match="no longer matches",
    ):

        tool.execute(
            symbol="run",
            expected_text=(
                "def run():\n"
                "    return 1"
            ),
            new_text=(
                "def run():\n"
                "    return 2"
            ),
        )


def test_symbol_index_refreshes_after_replacement(
    tmp_path: Path,
):

    (
        tmp_path
        / "demo.py"
    ).write_text(
        (
            "def old_name():\n"
            "    return 1\n"
        )
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    tool = ReplaceSymbolTool(
        workspace=tmp_path,
        symbol_index=index,
    )

    tool.execute(
        symbol="old_name",
        new_text=(
            "def new_name():\n"
            "    return 1"
        ),
    )

    old_matches = (
        index.search(
            "old_name"
        )
    )

    new_matches = (
        index.search(
            "new_name"
        )
    )

    assert (
        old_matches
        == []
    )

    assert (
        len(new_matches)
        == 1
    )