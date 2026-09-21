import ast
from pathlib import Path

from ..base import BaseTool
from ...utils.paths import resolve_workspace_path
from .replace_lines import ReplaceLinesTool
from ..results import ToolResult

from ...agent.context import (
    Symbol,
    SymbolIndex,
)
from ...agent.editing import EditFailureType
from ...agent.reason_codes import ReasonCode


class ReplaceSymbolTool(
    BaseTool
):

    name = "replace_symbol"
    capabilities = frozenset({"filesystem.write", "code.edit"})

    description = (
        "按结构化符号名替换 Python 类、函数、方法或异步函数。"
        "工具会解析最新符号范围、校验 Python 语法，"
        "并使用已验证的行范围编辑。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": (
                    "符号名或限定名。"
                    "示例：'Planner'、'create_plan'、"
                    "'MiniCodexAgent.replan'。"
                ),
            },
            "new_text": {
                "type": "string",
                "description": (
                    "所选符号的完整替换源代码。"
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "可选路径过滤，用于消歧义。"
                ),
            },
            "kind": {
                "type": "string",
                "description": (
                    "可选的精确符号类型：class、"
                    "function、method、async_function "
                    "或 async_method。"
                ),
            },
            "expected_text": {
                "type": "string",
                "description": (
                    "可选：当前符号应匹配的精确源码文本。"
                ),
            },
        },
        "required": [
            "symbol",
            "new_text",
        ],
    }

    def __init__(
        self,
        workspace: str | Path,
        symbol_index: SymbolIndex,
    ):
        self.workspace = Path(
            workspace
        ).resolve()

        self.symbol_index = (
            symbol_index
        )

        self.replace_lines = (
            ReplaceLinesTool(
                workspace=self.workspace
            )
        )

    # =========================================================
    # Execute
    # =========================================================

    def execute(
        self,
        symbol: str,
        new_text: str,
        path: str | None = None,
        kind: str | None = None,
        expected_text: str | None = None,
    ) -> ToolResult:

        symbol_query = (
            str(symbol)
            .strip()
        )

        if not symbol_query:

            raise ValueError(
                "符号名不能为空。"
            )

        if not str(
            new_text
        ).strip():

            raise ValueError(
                "new_text 不能为空。"
            )

        # =====================================================
        # Refresh Structural Source
        # =====================================================

        self.symbol_index.refresh()

        # =====================================================
        # Resolve Symbol
        # =====================================================

        target = (
            self._resolve_symbol(
                symbol_query,
                path=path,
                kind=kind,
            )
        )

        # =====================================================
        # Current Physical File
        # =====================================================

        file_path = (
            resolve_workspace_path(
                self.workspace,
                target.path,
            )
        )

        if not file_path.exists():

            raise FileNotFoundError(
                f"文件未找到：{target.path}"
            )

        source = (
            file_path.read_text(
                encoding="utf-8"
            )
        )

        lines = (
            source.splitlines()
        )

        if (
            target.end_line
            is None
        ):

            raise ValueError(
                (
                    f"符号 "
                    f"'{target.qualified_name}' "
                    "没有结束行。"
                )
            )

        start_line = (
            target.line
        )

        end_line = (
            target.end_line
        )

        current_text = (
            "\n".join(
                lines[
                    start_line - 1:
                    end_line
                ]
            )
        )

        # =====================================================
        # Optional Explicit Stale Guard
        # =====================================================

        if (
            expected_text
            is not None
        ):

            if (
                current_text
                != expected_text.rstrip(
                    "\n"
                )
            ):
                return ToolResult(
                    success=False,
                    summary=(
                        f"符号 {target.qualified_name} "
                        f"的替换上下文已过期。"
                    ),
                    data={
                        "path": target.path,
                        "checkpoint_id": None,
                        "symbol": target.qualified_name,
                        "start_line": start_line,
                        "end_line": end_line,
                        "changed": False,
                        "edit_kind": "symbol",
                        "failure_type": "stale_context",
                        "edit_failure_type": EditFailureType.STALE_CONTEXT.value,
                        "reason_code": ReasonCode.STALE_CONTEXT.value,
                        "retry_action": "read_target_region_then_retry_once",
                    },
                    error="当前符号已与 expected_text 不一致。",
                )

        # =====================================================
        # Prepare Indentation
        # =====================================================

        replacement_text = (
            self._prepare_replacement_text(
                new_text=(
                    new_text
                ),
                current_text=(
                    current_text
                ),
            )
        )

        # =====================================================
        # Candidate Syntax Preflight
        # =====================================================

        replacement_lines = (
            replacement_text
            .rstrip("\n")
            .splitlines()
        )

        candidate_lines = (
            lines[:start_line - 1]
            + replacement_lines
            + lines[end_line:]
        )

        candidate_source = (
            "\n".join(
                candidate_lines
            )
        )

        if source.endswith(
            "\n"
        ):

            candidate_source += "\n"

        try:

            ast.parse(
                candidate_source,
                filename=str(
                    file_path
                ),
            )

        except SyntaxError as e:

            raise ValueError(
                (
                    "替换将产生无效的 "
                    "Python 语法："
                    f"{e.msg} "
                    f"（第 {e.lineno} 行，"
                    f"第 {e.offset} 列）。"
                )
            ) from e

        # =====================================================
        # Verified Physical Edit
        # =====================================================

        replace_result = (
            self.replace_lines.execute(
                path=target.path,
                start_line=start_line,
                end_line=end_line,
                new_text=replacement_text,
                expected_text=current_text,
            )
        )

        # =====================================================
        # Refresh Symbol Index
        # =====================================================

        self.symbol_index.refresh()

        return ToolResult(
            success=True,
            summary=(
                f"已成功替换并校验符号 "
                f"{target.qualified_name} "
                f"（位于 {target.path}）。"
            ),
            data={
                "symbol": (
                    target.name
                ),
                "qualified_name": (
                    target.qualified_name
                ),
                "kind": (
                    target.kind
                ),
                "path": (
                    target.path
                ),
                "checkpoint_id": None,
                "edit_kind": "symbol",
                "old_start_line": (
                    start_line
                ),
                "old_end_line": (
                    end_line
                ),
                "new_start_line": (
                    replace_result.data[
                        "new_start_line"
                    ]
                ),
                "new_end_line": (
                    replace_result.data[
                        "new_end_line"
                    ]
                ),
                "changed": (
                    replace_result.data[
                        "changed"
                    ]
                ),
                "content_verified": (
                    replace_result.data[
                        "content_verified"
                    ]
                ),
                "syntax_validated": (
                    replace_result.data[
                        "syntax_validated"
                    ]
                ),
                "before_sha256": (
                    replace_result.data[
                        "before_sha256"
                    ]
                ),
                "after_sha256": (
                    replace_result.data[
                        "after_sha256"
                    ]
                ),
                "symbol_index_refreshed": (
                    True
                ),
            },
        )

    # =========================================================
    # Resolve Symbol
    # =========================================================

    def _resolve_symbol(
        self,
        query: str,
        *,
        path: str | None,
        kind: str | None,
    ) -> Symbol:

        matches = (
            self.symbol_index.search(
                query,
                kind=kind,
                path=path,
                max_results=200,
            )
        )

        normalized_query = (
            query.casefold()
        )

        qualified_matches = [
            candidate
            for candidate
            in matches
            if (
                candidate
                .qualified_name
                .casefold()
                == normalized_query
            )
        ]

        if (
            len(
                qualified_matches
            )
            == 1
        ):

            return (
                qualified_matches[0]
            )

        if (
            len(
                qualified_matches
            )
            > 1
        ):

            raise ValueError(
                self._ambiguous_message(
                    query,
                    qualified_matches,
                )
            )

        name_matches = [
            candidate
            for candidate
            in matches
            if (
                candidate
                .name
                .casefold()
                == normalized_query
            )
        ]

        if (
            len(
                name_matches
            )
            == 1
        ):

            return (
                name_matches[0]
            )

        if (
            len(
                name_matches
            )
            > 1
        ):

            raise ValueError(
                self._ambiguous_message(
                    query,
                    name_matches,
                )
            )

        if not matches:

            raise ValueError(
                (
                    f"未找到符号 '{query}'。"
                )
            )

        candidate_names = (
            ", ".join(
                candidate.qualified_name
                for candidate
                in matches[:10]
            )
        )

        raise ValueError(
            (
                f"没有与 '{query}' "
                f"精确匹配的符号。"
                f"可能的候选："
                f"{candidate_names}"
            )
        )

    # =========================================================
    # Ambiguity
    # =========================================================

    @staticmethod
    def _ambiguous_message(
        query: str,
        matches: list[Symbol],
    ) -> str:

        candidates = (
            ", ".join(
                (
                    f"{candidate.qualified_name} "
                    f"({candidate.path})"
                )
                for candidate
                in matches[:10]
            )
        )

        return (
            f"符号 '{query}' 匹配不唯一。"
            f"候选：{candidates}。"
            "请提供限定符号名"
            "或路径过滤条件。"
        )

    # =========================================================
    # Indentation
    # =========================================================

    @staticmethod
    def _prepare_replacement_text(
        new_text: str,
        current_text: str,
    ) -> str:

        replacement = (
            new_text.strip(
                "\n"
            )
        )

        current_first_line = (
            current_text
            .splitlines()[0]
        )

        current_indent = (
            current_first_line[
                :len(current_first_line)
                - len(
                    current_first_line
                    .lstrip()
                )
            ]
        )

        replacement_lines = (
            replacement.splitlines()
        )

        if not replacement_lines:

            return replacement

        first_line = (
            replacement_lines[0]
        )

        replacement_indent = (
            first_line[
                :len(first_line)
                - len(
                    first_line
                    .lstrip()
                )
            ]
        )

        if (
            replacement_indent
            == current_indent
        ):

            return replacement

        if not current_indent:

            return replacement

        if replacement_indent:

            return replacement

        return "\n".join(
            (
                current_indent
                + line
                if line
                else line
            )
            for line
            in replacement_lines
        )
