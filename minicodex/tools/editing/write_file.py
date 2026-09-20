from pathlib import Path

from ..base import BaseTool
from ...agent.editing import EditVerifier
from ...utils.paths import resolve_workspace_path
from ..results import ToolResult


class WriteFileTool(
    BaseTool
):

    name = "write_file"
    capabilities = frozenset({"filesystem.write", "code.edit"})

    description = (
        "在当前项目中创建新文本文件，或覆盖已有文本文件。"
        "主要用于新建文件或真正的整文件替换。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "要写入的文件相对路径，"
                    "例如 'calculator.py'。"
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "应写入文件的完整文本内容。"
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
                        "无法覆盖非文件路径："
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
                f"已成功覆盖并校验文件：{path}"
            )

        else:

            summary = (
                f"已成功创建并校验文件：{path}"
            )

        return ToolResult(
            success=True,
            summary=summary,
            data={
                "path": path,
                "checkpoint_id": None,
                "edit_kind": (
                    "create" if not existed_before else "full_replace"
                ),
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
