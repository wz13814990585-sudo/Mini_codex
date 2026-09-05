from pathlib import Path

from .base import BaseTool
from .edit_verifier import EditVerifier
from .paths import resolve_workspace_path
from .results import ToolResult


class ReplaceLinesTool(
    BaseTool
):

    name = "replace_lines"

    description = (
        "Replace an exact line range in an existing text file. "
        "Use this after read_file has verified the current range. "
        "The edit is checked before and after writing."
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Relative path of the file to modify."
                ),
            },
            "start_line": {
                "type": "integer",
                "description": (
                    "1-based first line to replace."
                ),
            },
            "end_line": {
                "type": "integer",
                "description": (
                    "1-based last line to replace, inclusive."
                ),
            },
            "new_text": {
                "type": "string",
                "description": (
                    "Replacement text for the requested "
                    "line range."
                ),
            },
            "expected_text": {
                "type": "string",
                "description": (
                    "Optional exact text expected in the "
                    "current line range. If it no longer "
                    "matches, the edit is rejected."
                ),
            },
        },
        "required": [
            "path",
            "start_line",
            "end_line",
            "new_text",
        ],
    }

    def __init__(
        self,
        workspace: str = ".",
    ):
        self.workspace = Path(
            workspace
        ).resolve()

    # =========================================================
    # Execute
    # =========================================================

    def execute(
        self,
        path: str,
        start_line: int,
        end_line: int,
        new_text: str,
        expected_text: str | None = None,
    ) -> ToolResult:

        file_path = (
            resolve_workspace_path(
                self.workspace,
                path,
            )
        )

        if not file_path.exists():

            raise FileNotFoundError(
                f"File not found: {path}"
            )

        if not file_path.is_file():

            raise ValueError(
                f"Path is not a file: {path}"
            )

        before_content = (
            file_path.read_text(
                encoding="utf-8"
            )
        )

        lines = (
            before_content
            .splitlines()
        )

        total_lines = (
            len(lines)
        )

        start = int(
            start_line
        )

        end = int(
            end_line
        )

        # =====================================================
        # Range Validation
        # =====================================================

        if start < 1:

            raise ValueError(
                "start_line must be >= 1."
            )

        if end < start:

            raise ValueError(
                (
                    "end_line must be "
                    ">= start_line."
                )
            )

        if end > total_lines:

            raise ValueError(
                (
                    f"Requested line range "
                    f"{start}-{end} exceeds "
                    f"file length {total_lines}."
                )
            )

        # =====================================================
        # Current Range
        # =====================================================

        current_lines = (
            lines[
                start - 1:end
            ]
        )

        current_text = (
            "\n".join(
                current_lines
            )
        )

        # =====================================================
        # Stale Source Guard
        # =====================================================

        if (
            expected_text
            is not None
        ):

            normalized_expected = (
                expected_text
                .rstrip("\n")
            )

            if (
                current_text
                != normalized_expected
            ):

                raise ValueError(
                    (
                        "The current file content no longer "
                        "matches expected_text for the requested "
                        f"range {start}-{end}. "
                        "Re-read the file before editing."
                    )
                )

        # =====================================================
        # Replacement
        # =====================================================

        replacement_lines = (
            new_text
            .rstrip("\n")
            .splitlines()
        )

        updated_lines = (
            lines[:start - 1]
            + replacement_lines
            + lines[end:]
        )

        updated_content = (
            "\n".join(
                updated_lines
            )
        )

        if before_content.endswith(
            "\n"
        ):

            updated_content += "\n"

        # =====================================================
        # Reject No-Op
        # =====================================================

        EditVerifier.ensure_changed(
            before_content,
            updated_content,
        )

        # =====================================================
        # Pre-Write Validation
        # =====================================================

        EditVerifier.validate_candidate(
            file_path,
            updated_content,
        )

        # =====================================================
        # Write
        # =====================================================

        file_path.write_text(
            updated_content,
            encoding="utf-8",
        )

        # =====================================================
        # Post-Write Verification
        # =====================================================

        verification = (
            EditVerifier
            .verify_after_write(
                file_path,
                before_content=(
                    before_content
                ),
                expected_content=(
                    updated_content
                ),
            )
        )

        new_end_line = (
            start
            + len(
                replacement_lines
            )
            - 1
        )

        return ToolResult(
            success=True,
            summary=(
                f"Successfully replaced and verified "
                f"{path} lines {start}-{end}."
            ),
            data={
                "path": path,
                "old_start_line": start,
                "old_end_line": end,
                "new_start_line": start,
                "new_end_line": (
                    new_end_line
                ),
                "old_line_count": (
                    end
                    - start
                    + 1
                ),
                "new_line_count": (
                    len(
                        replacement_lines
                    )
                ),
                "expected_text_checked": (
                    expected_text
                    is not None
                ),
                "changed": (
                    verification.changed
                ),
                "content_verified": (
                    verification
                    .content_verified
                ),
                "syntax_validated": (
                    verification
                    .syntax_validated
                ),
                "before_sha256": (
                    verification
                    .before_sha256
                ),
                "after_sha256": (
                    verification
                    .after_sha256
                ),
            },
        )