"""Code search tools."""

from pathlib import Path

from .base import BaseTool
from .paths import resolve_workspace_path
from .base import ToolResult


MAX_SEARCH_FILE_BYTES = 1_000_000
DEFAULT_MAX_RESULTS = 40


class SearchCodeTool(BaseTool):

    name = "search_code"

    description = (
        "Search for text inside project files and return matching "
        "file paths, line numbers, and matching lines."
    )

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Text to search for, for example "
                    "'def calculate' or 'FastAPI('."
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Optional relative directory to search. "
                    "Defaults to the project root."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "Maximum matches to return, from 1 to 200. "
                    "Defaults to 40."
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def execute(
        self,
        query: str,
        path: str = ".",
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> ToolResult:

        # Clamp the requested result limit to a safe range.
        result_limit = min(
            max(int(max_results), 1),
            200,
        )

        # We intentionally collect one extra match.
        #
        # Example:
        # max_results = 40
        #
        # If we find 41 matches, we know with certainty
        # that the visible results are truncated.
        collection_limit = result_limit + 1

        search_root = resolve_workspace_path(
            self.workspace,
            path,
        )

        if not search_root.exists():
            raise FileNotFoundError(
                f"Search path not found: {path}"
            )

        if not search_root.is_dir():
            raise ValueError(
                f"Search path is not a directory: {path}"
            )

        ignored_dirs = {
            ".git",
            "__pycache__",
            ".pytest_cache",
            ".venv",
            "venv",
            "node_modules",
            "build",
            "dist",
        }

        ignored_suffixes = {
            ".pyc",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".pdf",
            ".zip",
        }

        # Machine-readable search results.
        matches: list[dict] = []

        stop_search = False

        for file_path in search_root.rglob("*"):

            if not file_path.is_file():
                continue

            if any(
                part in ignored_dirs
                for part in file_path.parts
            ):
                continue

            if file_path.suffix.lower() in ignored_suffixes:
                continue

            try:
                if (
                    file_path.stat().st_size
                    > MAX_SEARCH_FILE_BYTES
                ):
                    continue
            except OSError:
                continue

            try:
                content = file_path.read_text(
                    encoding="utf-8"
                )
            except Exception:
                continue

            for line_number, line in enumerate(
                content.splitlines(),
                start=1,
            ):

                if query.lower() not in line.lower():
                    continue

                relative_path = file_path.relative_to(
                    self.workspace
                )

                matches.append(
                    {
                        "path": str(relative_path),
                        "line": line_number,
                        "text": line.strip(),
                    }
                )

                # Collect one extra result so that
                # truncation is based on real evidence.
                if len(matches) >= collection_limit:
                    stop_search = True
                    break

            if stop_search:
                break

        # If we collected more than the user-visible limit,
        # the search result is definitely truncated.
        truncated = len(matches) > result_limit

        visible_matches = matches[:result_limit]

        returned_match_count = len(
            visible_matches
        )

        # No matches is still a successful tool execution.
        if returned_match_count == 0:
            return ToolResult(
                success=True,
                summary=(
                    f"No matches found for '{query}'."
                ),
                data={
                    "query": query,
                    "search_path": path,
                    "returned_match_count": 0,
                    "truncated": False,
                    "max_results": result_limit,
                    "matches": [],
                },
                llm_content="",
            )

        # Build the text representation that the LLM sees.
        llm_lines = [
            (
                f"{match['path']}:"
                f"{match['line']}: "
                f"{match['text']}"
            )
            for match in visible_matches
        ]

        if truncated:
            llm_lines.append(
                (
                    "[Results truncated at "
                    f"{result_limit} matches]"
                )
            )

        llm_content = "\n".join(
            llm_lines
        )

        if truncated:
            summary = (
                f"Found at least "
                f"{returned_match_count} matches "
                f"for '{query}'; "
                "results were truncated."
            )
        else:
            summary = (
                f"Found "
                f"{returned_match_count} matches "
                f"for '{query}'."
            )

        return ToolResult(
            success=True,
            summary=summary,
            data={
                "query": query,
                "search_path": path,
                "returned_match_count": (
                    returned_match_count
                ),
                "truncated": truncated,
                "max_results": result_limit,
                "matches": visible_matches,
            },
            llm_content=llm_content,
        )