from pathlib import Path

from ..agent.symbol_index import (
    SymbolIndex,
)


def test_symbol_index_extracts_top_level_function(
    tmp_path: Path,
):

    (
        tmp_path
        / "demo.py"
    ).write_text(
        """
def hello(name):
    return name
""".strip()
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    index.refresh()

    matches = index.search(
        "hello"
    )

    assert (
        len(matches)
        == 1
    )

    symbol = (
        matches[0]
    )

    assert (
        symbol.name
        == "hello"
    )

    assert (
        symbol.qualified_name
        == "hello"
    )

    assert (
        symbol.kind
        == "function"
    )

    assert (
        symbol.path
        == "demo.py"
    )

    assert (
        symbol.line
        == 1
    )


def test_symbol_index_extracts_class_and_method(
    tmp_path: Path,
):

    (
        tmp_path
        / "agent.py"
    ).write_text(
        """
class Agent:

    def run(self):
        return "done"
""".strip()
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    index.refresh()

    class_matches = (
        index.search(
            "Agent",
            kind="class",
        )
    )

    assert (
        len(class_matches)
        == 1
    )

    assert (
        class_matches[0]
        .qualified_name
        == "Agent"
    )

    method_matches = (
        index.search(
            "Agent.run"
        )
    )

    assert (
        len(method_matches)
        == 1
    )

    assert (
        method_matches[0]
        .name
        == "run"
    )

    assert (
        method_matches[0]
        .qualified_name
        == "Agent.run"
    )

    assert (
        method_matches[0]
        .kind
        == "method"
    )


def test_symbol_index_extracts_async_function(
    tmp_path: Path,
):

    (
        tmp_path
        / "async_demo.py"
    ).write_text(
        """
async def fetch_data():
    return 1
""".strip()
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    index.refresh()

    matches = index.search(
        "fetch_data"
    )

    assert (
        len(matches)
        == 1
    )

    assert (
        matches[0].kind
        == "async_function"
    )


def test_symbol_index_extracts_async_method(
    tmp_path: Path,
):

    (
        tmp_path
        / "client.py"
    ).write_text(
        """
class Client:

    async def fetch(self):
        return 1
""".strip()
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    index.refresh()

    matches = index.search(
        "Client.fetch"
    )

    assert (
        len(matches)
        == 1
    )

    assert (
        matches[0].kind
        == "async_method"
    )


def test_symbol_index_ignores_non_python_files(
    tmp_path: Path,
):

    (
        tmp_path
        / "notes.txt"
    ).write_text(
        """
def fake_function():
    pass
""".strip()
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    index.refresh()

    matches = index.search(
        "fake_function"
    )

    assert (
        matches
        == []
    )


def test_symbol_index_survives_syntax_error(
    tmp_path: Path,
):

    (
        tmp_path
        / "broken.py"
    ).write_text(
        """
def broken(
""".strip()
    )

    (
        tmp_path
        / "good.py"
    ).write_text(
        """
def good():
    return True
""".strip()
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    index.refresh()

    assert (
        index.parse_errors
        == 1
    )

    matches = index.search(
        "good"
    )

    assert (
        len(matches)
        == 1
    )


def test_symbol_search_exact_match_ranks_first(
    tmp_path: Path,
):

    (
        tmp_path
        / "demo.py"
    ).write_text(
        """
def run():
    pass

def runner():
    pass

def rerun():
    pass
""".strip()
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    index.refresh()

    matches = index.search(
        "run"
    )

    assert (
        matches[0].name
        == "run"
    )


def test_symbol_search_path_filter(
    tmp_path: Path,
):

    first = (
        tmp_path
        / "first"
    )

    second = (
        tmp_path
        / "second"
    )

    first.mkdir()
    second.mkdir()

    (
        first
        / "service.py"
    ).write_text(
        """
def execute():
    pass
""".strip()
    )

    (
        second
        / "service.py"
    ).write_text(
        """
def execute():
    pass
""".strip()
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    index.refresh()

    matches = index.search(
        "execute",
        path="first",
    )

    assert (
        len(matches)
        == 1
    )

    assert (
        matches[0].path
        == "first/service.py"
    )
from pathlib import Path

from ..agent.symbol_index import (
    SymbolIndex,
)
from ..tools.search_symbol import (
    SearchSymbolTool,
)


def test_search_symbol_tool_returns_structured_result(
    tmp_path: Path,
):

    (
        tmp_path
        / "agent.py"
    ).write_text(
        """
class Agent:

    def run(self):
        return "done"
""".strip()
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    tool = SearchSymbolTool(
        symbol_index=index
    )

    result = tool.execute(
        query="Agent.run"
    )

    assert (
        result.success
        is True
    )

    assert (
        result.data[
            "returned_match_count"
        ]
        == 1
    )

    match = (
        result.data[
            "matches"
        ][0]
    )

    assert (
        match["qualified_name"]
        == "Agent.run"
    )

    assert (
        match["kind"]
        == "method"
    )

    assert (
        match["path"]
        == "agent.py"
    )

    assert (
        "Agent.run"
        in result.llm_content
    )


def test_search_symbol_tool_refreshes_index(
    tmp_path: Path,
):

    index = SymbolIndex(
        workspace=tmp_path
    )

    tool = SearchSymbolTool(
        symbol_index=index
    )

    first = tool.execute(
        query="NewAgent"
    )

    assert (
        first.data[
            "returned_match_count"
        ]
        == 0
    )

    (
        tmp_path
        / "new_agent.py"
    ).write_text(
        """
class NewAgent:
    pass
""".strip()
    )

    second = tool.execute(
        query="NewAgent"
    )

    assert (
        second.data[
            "returned_match_count"
        ]
        == 1
    )


def test_search_symbol_tool_kind_filter(
    tmp_path: Path,
):

    (
        tmp_path
        / "demo.py"
    ).write_text(
        """
class Runner:
    pass

def Runner():
    pass
""".strip()
    )

    index = SymbolIndex(
        workspace=tmp_path
    )

    tool = SearchSymbolTool(
        symbol_index=index
    )

    result = tool.execute(
        query="Runner",
        kind="class",
    )

    assert (
        result.data[
            "returned_match_count"
        ]
        == 1
    )

    assert (
        result.data[
            "matches"
        ][0]["kind"]
        == "class"
    )

from pathlib import Path

from ..agent.symbol_index import (
    SymbolIndex,
)
from ..tools.registry import (
    ToolRegistry,
)
from ..tools.search_symbol import (
    SearchSymbolTool,
)


def test_search_symbol_registered_schema(
    tmp_path: Path,
):

    symbol_index = SymbolIndex(
        workspace=tmp_path
    )

    registry = ToolRegistry()

    registry.register(
        SearchSymbolTool(
            symbol_index=(
                symbol_index
            )
        )
    )

    schemas = (
        registry.get_schemas()
    )

    assert (
        len(schemas)
        == 1
    )

    schema = (
        schemas[0]
    )

    assert (
        schema["type"]
        == "function"
    )

    function_schema = (
        schema["function"]
    )

    assert (
        function_schema["name"]
        == "search_symbol"
    )

    properties = (
        function_schema[
            "parameters"
        ][
            "properties"
        ]
    )

    assert (
        "query"
        in properties
    )

    assert (
        "kind"
        in properties
    )

    assert (
        "path"
        in properties
    )

    assert (
        "max_results"
        in properties
    )


def test_registry_executes_search_symbol(
    tmp_path: Path,
):

    (
        tmp_path
        / "agent.py"
    ).write_text(
        """
class Agent:

    def run(self):
        return "done"
""".strip()
    )

    symbol_index = SymbolIndex(
        workspace=tmp_path
    )

    registry = ToolRegistry()

    registry.register(
        SearchSymbolTool(
            symbol_index=(
                symbol_index
            )
        )
    )

    result = registry.execute(
        "search_symbol",
        {
            "query": (
                "Agent.run"
            )
        },
    )

    assert (
        result.success
        is True
    )

    assert (
        result.data[
            "returned_match_count"
        ]
        == 1
    )

    assert (
        result.data[
            "matches"
        ][0][
            "qualified_name"
        ]
        == "Agent.run"
    )

from pathlib import Path

from ..agent.symbol_index import (
    SymbolIndex,
)
from ..tools.search_symbol import (
    SearchSymbolTool,
)
from ..tools.read_file import (
    ReadFileTool,
)


def test_symbol_location_can_drive_read_file(
    tmp_path: Path,
):

    (
        tmp_path
        / "agent.py"
    ).write_text(
        """
class Agent:

    def first(self):
        return 1

    def run(self):
        value = 10
        return value

    def last(self):
        return 3
""".strip()
    )

    symbol_index = SymbolIndex(
        workspace=tmp_path
    )

    symbol_tool = SearchSymbolTool(
        symbol_index=(
            symbol_index
        )
    )

    read_tool = ReadFileTool(
        workspace=tmp_path
    )

    # =========================================================
    # Locate Symbol
    # =========================================================

    symbol_result = (
        symbol_tool.execute(
            query="Agent.run"
        )
    )

    assert (
        symbol_result.success
        is True
    )

    match = (
        symbol_result.data[
            "matches"
        ][0]
    )

    # =========================================================
    # Read Source Around Symbol
    # =========================================================

    start_line = (
        match["line"]
    )

    end_line = (
        match["end_line"]
    )

    limit = (
        end_line
        - start_line
        + 1
    )

    read_result = (
        read_tool.execute(
            path=match["path"],
            offset=start_line,
            limit=limit,
        )
    )

    assert (
        read_result.success
        is True
    )

    assert (
        "def run(self)"
        in read_result.llm_content
    )

    assert (
        "value = 10"
        in read_result.llm_content
    )

    assert (
        "return value"
        in read_result.llm_content
    )