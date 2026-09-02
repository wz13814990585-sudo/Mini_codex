"""Code search tools."""
from pathlib import Path

from tools.base import BaseTool


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
            }
        },
        "required": ["query"]
    }

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def execute(self, query: str) -> str:

        results = []

        ignored_dirs = {
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "node_modules"
        }

        for file_path in self.workspace.rglob("*"):

            if not file_path.is_file():
                continue

            if any(
                part in ignored_dirs
                for part in file_path.parts
            ):
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

        if not results:
            return f"No matches found for: {query}"

        return "\n".join(results[:100])