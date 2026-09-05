import ast
from pathlib import Path

from .base import BaseTool
from .paths import resolve_workspace_path
from .replace_lines import ReplaceLinesTool
from .results import ToolResult

from ..agent.symbol_index import (
    Symbol,
    SymbolIndex,
)


class ReplaceSymbolTool(
    BaseTool
):

    name = "replace_symbol"

    description = (
        "Replace a Python class, function, method, or async "
        "function by structural symbol name. The tool resolves "
        "the latest symbol range, validates Python syntax, and "
        "uses verified line-range editing."
    )

    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": (
                    "Symbol name or qualified name. "
                    "Examples: 'Planner', 'create_plan', "
                    "'MiniCodexAgent.replan'."
                ),
            },
            "new_text": {
                "type": "string",
                "description": (
                    "Complete replacement source code "
                    "for the selected symbol."
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Optional path filter used to "
                    "disambiguate symbols."
                ),
            },
            "kind": {
                "type": "string",
                "description": (
                    "Optional exact symbol kind: class, "
                    "function, method, async_function, "
                    "or async_method."
                ),
            },
            "expected_text": {
                "type": "string",
                "description": (
                    "Optional exact source text expected "
                    "for the current symbol."
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
                "Symbol name cannot be empty."
            )

        if not str(
            new_text
        ).strip():

            raise ValueError(
                "new_text cannot be empty."
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
                f"File not found: {target.path}"
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
                    f"Symbol "
                    f"'{target.qualified_name}' "
                    "does not have an end line."
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

                raise ValueError(
                    (
                        "The current symbol source no longer "
                        "matches expected_text. "
                        "Re-read the symbol before editing."
                    )
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
                    "Replacement would produce invalid "
                    "Python syntax: "
                    f"{e.msg} "
                    f"(line {e.lineno}, "
                    f"column {e.offset})."
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
                f"Successfully replaced and verified "
                f"symbol {target.qualified_name} "
                f"in {target.path}."
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
                    f"Symbol '{query}' "
                    "was not found."
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
                f"No exact symbol match "
                f"for '{query}'. "
                f"Possible candidates: "
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
            f"Symbol '{query}' is ambiguous. "
            f"Candidates: {candidates}. "
            "Provide a qualified symbol name "
            "or a path filter."
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