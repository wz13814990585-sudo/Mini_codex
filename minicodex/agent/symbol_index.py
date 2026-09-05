import ast
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_IGNORED_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
}


@dataclass(frozen=True)
class Symbol:
    """
    One structural Python code symbol.
    """

    name: str
    qualified_name: str
    kind: str
    path: str
    line: int
    end_line: int | None
    parent: str | None = None


class SymbolIndex:
    """
    AST-powered structural index for Python code.

    Stage 7 intentionally extracts only high-value
    symbols rather than exposing the entire AST.
    """

    def __init__(
        self,
        workspace: str | Path = ".",
        max_files: int = 500,
    ):
        self.workspace = Path(
            workspace
        ).resolve()

        self.max_files = (
            max(
                int(max_files),
                1,
            )
        )

        self.symbols: list[Symbol] = []

        self.indexed_files = 0
        self.parse_errors = 0

    # =========================================================
    # Refresh
    # =========================================================

    def refresh(
        self,
    ) -> None:
        """
        Rebuild the symbol index from the current workspace.
        """

        self.symbols = []
        self.indexed_files = 0
        self.parse_errors = 0

        if not self.workspace.exists():
            return

        if not self.workspace.is_dir():
            return

        for file_path in self._python_files():

            self._index_file(
                file_path
            )

            self.indexed_files += 1

            if (
                self.indexed_files
                >= self.max_files
            ):
                break

        self.symbols.sort(
            key=lambda symbol: (
                symbol.path.casefold(),
                symbol.line,
                symbol.qualified_name.casefold(),
            )
        )

    # =========================================================
    # Search
    # =========================================================

    def search(
        self,
        query: str,
        *,
        kind: str | None = None,
        path: str | None = None,
        max_results: int = 40,
    ) -> list[Symbol]:
        """
        Search indexed symbols.

        Matching checks both the short symbol name and
        its qualified name.

        Exact matches are ranked before prefix matches,
        then substring matches.
        """

        normalized_query = (
            str(query)
            .strip()
            .casefold()
        )

        if not normalized_query:
            return []

        normalized_kind = (
            str(kind)
            .strip()
            .casefold()
            if kind
            else None
        )

        normalized_path = (
            str(path)
            .strip()
            .casefold()
            if path
            else None
        )

        result_limit = min(
            max(
                int(max_results),
                1,
            ),
            200,
        )

        ranked_matches = []

        for symbol in self.symbols:

            if (
                normalized_kind
                and symbol.kind.casefold()
                != normalized_kind
            ):
                continue

            if (
                normalized_path
                and normalized_path
                not in symbol.path.casefold()
            ):
                continue

            name = (
                symbol.name.casefold()
            )

            qualified_name = (
                symbol.qualified_name
                .casefold()
            )

            rank = self._match_rank(
                normalized_query,
                name,
                qualified_name,
            )

            if rank is None:
                continue

            ranked_matches.append(
                (
                    rank,
                    symbol,
                )
            )

        ranked_matches.sort(
            key=lambda item: (
                item[0],
                item[1].path.casefold(),
                item[1].line,
            )
        )

        return [
            symbol
            for _, symbol
            in ranked_matches[
                :result_limit
            ]
        ]

    # =========================================================
    # Match Ranking
    # =========================================================

    @staticmethod
    def _match_rank(
        query: str,
        name: str,
        qualified_name: str,
    ) -> int | None:

        if (
            query == name
            or query == qualified_name
        ):
            return 0

        if (
            name.startswith(
                query
            )
            or qualified_name.startswith(
                query
            )
        ):
            return 1

        if (
            query in name
            or query in qualified_name
        ):
            return 2

        return None

    # =========================================================
    # Python File Discovery
    # =========================================================

    def _python_files(
        self,
    ):

        for (
            current_root,
            dir_names,
            file_names,
        ) in os.walk(
            self.workspace
        ):

            # Prune ignored directories before descending.
            dir_names[:] = sorted(
                [
                    directory
                    for directory
                    in dir_names
                    if (
                        directory
                        not in DEFAULT_IGNORED_DIRS
                    )
                ],
                key=str.casefold,
            )

            current_path = Path(
                current_root
            )

            for file_name in sorted(
                file_names,
                key=str.casefold,
            ):

                if not file_name.endswith(
                    ".py"
                ):
                    continue

                yield (
                    current_path
                    / file_name
                )

    # =========================================================
    # Index One File
    # =========================================================

    def _index_file(
        self,
        file_path: Path,
    ) -> None:

        try:

            source = (
                file_path.read_text(
                    encoding="utf-8"
                )
            )

        except Exception:

            return

        try:

            tree = ast.parse(
                source,
                filename=str(
                    file_path
                ),
            )

        except SyntaxError:

            self.parse_errors += 1

            return

        relative_path = str(
            file_path.relative_to(
                self.workspace
            )
        )

        self._extract_from_body(
            tree.body,
            relative_path=relative_path,
            parent=None,
        )

    # =========================================================
    # Extract Symbols
    # =========================================================

    def _extract_from_body(
        self,
        body: list,
        *,
        relative_path: str,
        parent: str | None,
    ) -> None:

        for node in body:

            # =================================================
            # Class
            # =================================================

            if isinstance(
                node,
                ast.ClassDef,
            ):

                qualified_name = (
                    f"{parent}.{node.name}"
                    if parent
                    else node.name
                )

                self.symbols.append(
                    Symbol(
                        name=node.name,
                        qualified_name=(
                            qualified_name
                        ),
                        kind="class",
                        path=relative_path,
                        line=node.lineno,
                        end_line=getattr(
                            node,
                            "end_lineno",
                            None,
                        ),
                        parent=parent,
                    )
                )

                self._extract_from_body(
                    node.body,
                    relative_path=(
                        relative_path
                    ),
                    parent=(
                        qualified_name
                    ),
                )

                continue

            # =================================================
            # Async Function / Method
            # =================================================

            if isinstance(
                node,
                ast.AsyncFunctionDef,
            ):

                self._record_function(
                    node,
                    relative_path=(
                        relative_path
                    ),
                    parent=parent,
                    async_function=True,
                )

                continue

            # =================================================
            # Function / Method
            # =================================================

            if isinstance(
                node,
                ast.FunctionDef,
            ):

                self._record_function(
                    node,
                    relative_path=(
                        relative_path
                    ),
                    parent=parent,
                    async_function=False,
                )

    # =========================================================
    # Record Function
    # =========================================================

    def _record_function(
        self,
        node,
        *,
        relative_path: str,
        parent: str | None,
        async_function: bool,
    ) -> None:

        qualified_name = (
            f"{parent}.{node.name}"
            if parent
            else node.name
        )

        if parent:

            kind = (
                "async_method"
                if async_function
                else "method"
            )

        else:

            kind = (
                "async_function"
                if async_function
                else "function"
            )

        self.symbols.append(
            Symbol(
                name=node.name,
                qualified_name=(
                    qualified_name
                ),
                kind=kind,
                path=relative_path,
                line=node.lineno,
                end_line=getattr(
                    node,
                    "end_lineno",
                    None,
                ),
                parent=parent,
            )
        )