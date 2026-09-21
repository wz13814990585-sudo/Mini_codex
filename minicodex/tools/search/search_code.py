"""Code search tools."""

from pathlib import Path

from ..base import BaseTool
from ...utils.paths import resolve_workspace_path
from ..results import ToolResult


MAX_SEARCH_FILE_BYTES = 1_000_000
DEFAULT_MAX_RESULTS = 40


class SearchCodeTool(BaseTool):
    capabilities = frozenset({"code.search"})

    name = "search_code"

    description = (
        "在项目文件中搜索文本，返回匹配的文件路径、"
        "行号以及匹配行内容。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "要搜索的文本，例如 "
                    "'def calculate' 或 'FastAPI('。"
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "可选的相对文件或目录搜索范围。"
                    "默认为项目根目录。"
                ),
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "最多返回的匹配数，范围 1 到 200。"
                    "默认为 40。"
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
                f"搜索路径未找到：{path}"
            )

        if search_root.is_file():
            candidate_files = [search_root]

        elif search_root.is_dir():
            candidate_files = search_root.rglob("*")

        else:
            raise ValueError(
                f"搜索路径不是文件或目录：{path}"
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

        for file_path in candidate_files:

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
                    f"未找到与 '{query}' 匹配的结果。"
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
                    f"[结果已截断，最多显示 "
                    f"{result_limit} 条匹配]"
                )
            )

        llm_content = "\n".join(
            llm_lines
        )

        if truncated:
            summary = (
                f"至少找到 "
                f"{returned_match_count} 条与 "
                f"'{query}' 的匹配；"
                "结果已被截断。"
            )
        else:
            summary = (
                f"找到 "
                f"{returned_match_count} 条与 "
                f"'{query}' 的匹配。"
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
