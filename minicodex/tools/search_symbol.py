from .base import BaseTool
from .results import ToolResult

from ..agent.symbol_index import (
    SymbolIndex,
)


DEFAULT_MAX_RESULTS = 40


class SearchSymbolTool(
    BaseTool
):

    name = "search_symbol"

    description = (
        "Search Python code symbols using the AST-based "
        "symbol index. Use this to locate classes, "
        "functions, methods, and async functions before "
        "reading or editing their source code."
    )

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Symbol name or qualified symbol name. "
                    "Examples: 'run', 'MiniCodexAgent.run', "
                    "'Planner', or 'create_plan'."
                ),
            },
            "kind": {
                "type": "string",
                "description": (
                    "Optional exact symbol kind: "
                    "class, function, method, "
                    "async_function, or async_method."
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Optional path filter. "
                    "Example: 'minicodex/agent'."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "Maximum number of symbols to return, "
                    "from 1 to 200. Defaults to 40."
                ),
            },
        },
        "required": [
            "query"
        ],
    }

    def __init__(
        self,
        symbol_index: SymbolIndex,
    ):
        self.symbol_index = (
            symbol_index
        )

    def execute(
        self,
        query: str,
        kind: str | None = None,
        path: str | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> ToolResult:

        query = (
            str(query)
            .strip()
        )

        if not query:

            raise ValueError(
                "Symbol query cannot be empty."
            )

        valid_kinds = {
            "class",
            "function",
            "method",
            "async_function",
            "async_method",
        }

        normalized_kind = None

        if kind is not None:

            normalized_kind = (
                str(kind)
                .strip()
                .casefold()
            )

            if (
                normalized_kind
                not in valid_kinds
            ):

                raise ValueError(
                    "Invalid symbol kind: "
                    f"{kind}. "
                    "Expected one of: "
                    + ", ".join(
                        sorted(
                            valid_kinds
                        )
                    )
                )

        result_limit = min(
            max(
                int(max_results),
                1,
            ),
            200,
        )

        # =====================================================
        # Refresh Before Search
        #
        # This prevents stale symbols after write/patch.
        # =====================================================

        self.symbol_index.refresh()

        matches = (
            self.symbol_index.search(
                query,
                kind=normalized_kind,
                path=path,
                max_results=result_limit,
            )
        )

        if not matches:

            return ToolResult(
                success=True,
                summary=(
                    "No code symbols found "
                    f"for '{query}'."
                ),
                data={
                    "query": query,
                    "kind": (
                        normalized_kind
                    ),
                    "path": path,
                    "returned_match_count": 0,
                    "indexed_files": (
                        self.symbol_index
                        .indexed_files
                    ),
                    "parse_errors": (
                        self.symbol_index
                        .parse_errors
                    ),
                    "matches": [],
                },
                llm_content="",
            )

        match_data = [
            {
                "name": (
                    symbol.name
                ),
                "qualified_name": (
                    symbol.qualified_name
                ),
                "kind": (
                    symbol.kind
                ),
                "path": (
                    symbol.path
                ),
                "line": (
                    symbol.line
                ),
                "end_line": (
                    symbol.end_line
                ),
                "parent": (
                    symbol.parent
                ),
            }
            for symbol
            in matches
        ]

        llm_lines = []

        for symbol in matches:

            if (
                symbol.end_line
                is not None
            ):

                location = (
                    f"{symbol.line}-"
                    f"{symbol.end_line}"
                )

            else:

                location = str(
                    symbol.line
                )

            llm_lines.append(
                (
                    f"[{symbol.kind}] "
                    f"{symbol.qualified_name} "
                    f"— {symbol.path}:"
                    f"{location}"
                )
            )

        return ToolResult(
            success=True,
            summary=(
                f"Found "
                f"{len(matches)} "
                f"symbol matches "
                f"for '{query}'."
            ),
            data={
                "query": query,
                "kind": normalized_kind,
                "path": path,
                "returned_match_count": (
                    len(matches)
                ),
                "indexed_files": (
                    self.symbol_index
                    .indexed_files
                ),
                "parse_errors": (
                    self.symbol_index
                    .parse_errors
                ),
                "matches": (
                    match_data
                ),
            },
            llm_content=(
                "\n".join(
                    llm_lines
                )
            ),
        )