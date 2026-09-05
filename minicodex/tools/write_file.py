from pathlib import Path

from .base import BaseTool
from .edit_verifier import EditVerifier
from .paths import resolve_workspace_path
from .results import ToolResult


class WriteFileTool(
    BaseTool
):

    name = "write_file"

    description = (
        "Create a new text file or overwrite an existing "
        "text file inside the current project. Use mainly "
        "for new files or genuine full-file replacement."
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Relative path of the file to write, "
                    "for example 'calculator.py'."
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "The complete text content that "
                    "should be written to the file."
                ),
            },
        },
        "required": [
            "path",
            "content",
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
        content: str,
    ) -> ToolResult:

        file_path = (
            resolve_workspace_path(
                self.workspace,
                path,
            )
        )

        existed_before = (
            file_path.exists()
        )

        before_content = None

        if existed_before:

            if not file_path.is_file():

                raise ValueError(
                    (
                        "Cannot overwrite non-file path: "
                        f"{path}"
                    )
                )

            before_content = (
                file_path.read_text(
                    encoding="utf-8"
                )
            )

            # =================================================
            # Reject No-Op Overwrite
            # =================================================

            EditVerifier.ensure_changed(
                before_content,
                content,
            )

        # =====================================================
        # Validate Candidate Before Write
        # =====================================================

        EditVerifier.validate_candidate(
            file_path,
            content,
        )

        # =====================================================
        # Parent Directory
        # =====================================================

        file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # =====================================================
        # Write
        # =====================================================

        file_path.write_text(
            content,
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
                    content
                ),
            )
        )

        if existed_before:

            summary = (
                f"Successfully overwrote "
                f"and verified file: {path}"
            )

        else:

            summary = (
                f"Successfully created "
                f"and verified file: {path}"
            )

        return ToolResult(
            success=True,
            summary=summary,
            data={
                "path": path,
                "created": (
                    not existed_before
                ),
                "overwritten": (
                    existed_before
                ),
                "chars_written": (
                    len(content)
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