from ..base import BaseTool
from ..results import ToolResult

from ...agent.context import (
    SymbolIndex,
)


DEFAULT_MAX_RESULTS = 40


class SearchSymbolTool(
    BaseTool
):

    name = "search_symbol"
    capabilities = frozenset({"code.search", "code.symbol"})

    description = (
        "使用基于 AST 的符号索引搜索 Python 代码符号。"
        "在阅读或编辑源码前，用此工具定位类、函数、"
        "方法以及异步函数。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "符号名或限定符号名。"
                    "示例：'run'、'MiniCodexAgent.run'、"
                    "'Planner' 或 'create_plan'。"
                ),
            },
            "kind": {
                "type": "string",
                "description": (
                    "可选的精确符号类型："
                    "class、function、method、"
                    "async_function 或 async_method。"
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "可选的路径过滤条件。"
                    "示例：'minicodex/agent'。"
                ),
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "最多返回的符号数，范围 1 到 200。"
                    "默认为 40。"
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
                "符号查询不能为空。"
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
                    "无效的符号类型："
                    f"{kind}。"
                    "期望为以下之一："
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
                    "未找到与 "
                    f"'{query}' 匹配的代码符号。"
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
                f"找到 "
                f"{len(matches)} "
                f"个与 "
                f"'{query}' 匹配的符号。"
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
