"""Patch application tools."""

from pathlib import Path

from ..base import BaseTool
from ...agent.editing import EditVerifier
from ...utils.paths import resolve_workspace_path
from ..results import ToolResult
from ...agent.editing import EditFailureType
from ...agent.reason_codes import ReasonCode


class PatchFileTool(
    BaseTool
):

    name = "patch_file"
    capabilities = frozenset({"filesystem.write", "code.edit"})

    description = (
        "在已有项目文件中替换一段完全匹配且唯一的文本。"
        "在已知当前精确源码时，用于小范围定向修改。"
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
            "old_text": {
                "type": "string",
                "description": (
                    "应被替换的、当前文件中的精确原文。"
                ),
            },
            "new_text": {
                "type": "string",
                "description": (
                    "用于替换 old_text 的新文本。"
                ),
            },
        },
        "required": [
            "path",
            "old_text",
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
        old_text: str,
        new_text: str,
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

        # =====================================================
        # Exact Target Validation
        # =====================================================

        count = (
            before_content.count(
                old_text
            )
        )

        if count == 0:
            return ToolResult(
                success=False,
                summary=f"{path} 的补丁上下文已过期。",
                data={
                    "path": path,
                    "checkpoint_id": None,
                    "changed": False,
                    "edit_kind": "exact_patch",
                    "failure_type": "stale_context",
                    "edit_failure_type": EditFailureType.STALE_CONTEXT.value,
                    "reason_code": ReasonCode.STALE_CONTEXT.value,
                    "retry_action": "read_target_region_then_retry_once",
                    "current_content": before_content[:4_000],
                },
                error="当前文件中未找到 old_text。",
            )

        if count > 1:
            return ToolResult(
                success=False,
                summary=f"{path} 的补丁上下文不唯一。",
                data={
                    "path": path,
                    "checkpoint_id": None,
                    "changed": False,
                    "edit_kind": "exact_patch",
                    "failure_type": "ambiguous_match",
                    "edit_failure_type": EditFailureType.AMBIGUOUS_MATCH.value,
                    "reason_code": ReasonCode.AMBIGUOUS_MATCH.value,
                    "match_count": count,
                    "retry_action": "read_target_region_then_use_more_specific_context",
                },
                error="old_text 在文件中出现多次。",
            )

        # =====================================================
        # Candidate
        # =====================================================

        updated_content = (
            before_content.replace(
                old_text,
                new_text,
                1,
            )
        )

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

        return ToolResult(
            success=True,
            summary=(
                f"已成功打补丁并校验文件：{path}"
            ),
            data={
                "path": path,
                "checkpoint_id": None,
                "edit_kind": "exact_patch",
                "replacement_count": 1,
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
