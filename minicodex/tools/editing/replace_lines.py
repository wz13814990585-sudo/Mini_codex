from pathlib import Path

from ..base import BaseTool
from ...agent.editing import EditVerifier
from ...utils.paths import resolve_workspace_path
from ..results import ToolResult
from ...agent.editing import EditFailureType
from ...agent.reason_codes import ReasonCode


class ReplaceLinesTool(
    BaseTool
):

    name = "replace_lines"
    capabilities = frozenset({"filesystem.write", "code.edit"})

    description = (
        "替换已有文本文件中的精确行范围。"
        "请先用 read_file 确认当前范围后再调用。"
        "写入前后都会进行校验。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "要修改的文件相对路径。"
                ),
            },
            "start_line": {
                "type": "integer",
                "description": (
                    "要替换的起始行（从 1 起算）。"
                ),
            },
            "end_line": {
                "type": "integer",
                "description": (
                    "要替换的结束行（从 1 起算，含该行）。"
                ),
            },
            "new_text": {
                "type": "string",
                "description": (
                    "用于替换指定行范围的新文本。"
                ),
            },
            "expected_text": {
                "type": "string",
                "description": (
                    "可选：当前行范围应匹配的精确文本。"
                    "若不匹配，则拒绝本次编辑。"
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
                f"文件未找到：{path}"
            )

        if not file_path.is_file():

            raise ValueError(
                f"路径不是文件：{path}"
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
                "start_line 必须 >= 1。"
            )

        if end < start:

            raise ValueError(
                (
                    "end_line 必须 "
                    ">= start_line。"
                )
            )

        if end > total_lines:

            raise ValueError(
                (
                    f"请求的行范围 "
                    f"{start}-{end} 超出 "
                    f"文件长度 {total_lines}。"
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
                return ToolResult(
                    success=False,
                    summary=(
                        f"{path} 第 {start}-{end} 行的"
                        f"行替换上下文已过期。"
                    ),
                    data={
                        "path": path,
                        "checkpoint_id": None,
                        "start_line": start,
                        "end_line": end,
                        "changed": False,
                        "edit_kind": "line_range",
                        "failure_type": "stale_context",
                        "edit_failure_type": EditFailureType.STALE_CONTEXT.value,
                        "reason_code": ReasonCode.STALE_CONTEXT.value,
                        "retry_action": "read_target_region_then_retry_once",
                    },
                    error=(
                        "当前行范围已与 expected_text 不一致。"
                    ),
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
                f"已成功替换并校验 "
                f"{path} 第 {start}-{end} 行。"
            ),
            data={
                "path": path,
                "checkpoint_id": None,
                "edit_kind": "line_range",
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
