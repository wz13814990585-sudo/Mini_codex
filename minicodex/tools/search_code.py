"""Code search tools."""
from pathlib import Path

from minicodex.tools.base import BaseTool
from minicodex.tools.paths import resolve_workspace_path


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
                )
            },
            "path": {
                "type": "string",
                "description": (
                    "Optional relative directory to search. "
                    "Defaults to the project root."
                )
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "Maximum matches to return, from 1 to 200. "
                    "Defaults to 40."
                )
            },
        },
        "required": ["query"]
    }

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def execute(
        self,
        query: str,
        path: str = ".",
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> str:

        results = []
        result_limit = min(max(int(max_results), 1), 200)
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

        truncated = False

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
                if file_path.stat().st_size > MAX_SEARCH_FILE_BYTES:
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
                start=1
            ):
                if query.lower() in line.lower():

                    relative_path = file_path.relative_to(
                        self.workspace
                    )

                    results.append(
                        f"{relative_path}:{line_number}: {line.strip()}"
                    )

                    if len(results) > result_limit:
                        results.pop()
                        truncated = True
                        break

            if truncated:
                break

        if not results:
            return f"No matches found for: {query}"

        if truncated:
            results.append(
                f"[Results truncated at {result_limit} matches]"
            )

        return "\n".join(results)
