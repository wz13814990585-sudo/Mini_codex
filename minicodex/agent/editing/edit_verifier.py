import ast
import hashlib
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

DEFER_SYNTAX = ContextVar("defer_edit_syntax", default=False)


@dataclass(frozen=True)
class EditVerification:
    """
    Deterministic verification result for one edit.
    """

    changed: bool
    content_verified: bool
    syntax_validated: bool
    before_sha256: str | None
    after_sha256: str


class EditVerifier:
    """
    Shared deterministic verification for file edits.

    Responsibilities:

    1. Reject no-op edits.
    2. Validate Python syntax before writing.
    3. Re-read the file after writing.
    4. Confirm disk content exactly matches expectation.
    5. Validate Python syntax again after writing.
    6. Produce before/after content hashes.

    This component does not decide WHAT should be edited.
    That remains an LLM / orchestration responsibility.
    """

    # =========================================================
    # SHA256
    # =========================================================

    @staticmethod
    def content_hash(
        content: str,
    ) -> str:

        return hashlib.sha256(
            content.encode(
                "utf-8"
            )
        ).hexdigest()

    # =========================================================
    # Ensure Real Change
    # =========================================================

    @classmethod
    def ensure_changed(
        cls,
        before_content: str,
        after_content: str,
    ) -> None:

        if (
            before_content
            == after_content
        ):

            raise ValueError(
                "编辑不会改变文件内容。"
            )

    # =========================================================
    # Candidate Validation
    # =========================================================

    @staticmethod
    def validate_candidate(
        file_path: Path,
        content: str,
    ) -> bool:
        """
        Validate candidate content before writing.

        Currently Python receives AST syntax validation.
        Other text files require no language-level validation.

        Returns True when Python syntax was validated,
        otherwise False.
        """

        if (
            file_path.suffix.lower()
            != ".py"
        ):

            return False

        try:

            ast.parse(
                content,
                filename=str(
                    file_path
                ),
            )

        except SyntaxError as e:

            if DEFER_SYNTAX.get():
                return False

            raise ValueError(
                (
                    "编辑将产生无效的 "
                    "Python 语法："
                    f"{e.msg} "
                    f"（第 {e.lineno} 行，"
                    f"第 {e.offset} 列）。"
                )
            ) from e

        return True

    # =========================================================
    # Post-Write Verification
    # =========================================================

    @classmethod
    def verify_after_write(
        cls,
        file_path: Path,
        *,
        before_content: str | None,
        expected_content: str,
    ) -> EditVerification:
        """
        Re-read the physical file and verify that the
        expected edit actually reached disk.
        """

        if not file_path.exists():

            raise RuntimeError(
                (
                    "编辑后校验失败："
                    "写入后文件不存在。"
                )
            )

        if not file_path.is_file():

            raise RuntimeError(
                (
                    "编辑后校验失败："
                    "写入后路径不是文件。"
                )
            )

        actual_content = (
            file_path.read_text(
                encoding="utf-8"
            )
        )

        # =====================================================
        # Exact Disk Verification
        # =====================================================

        if (
            actual_content
            != expected_content
        ):

            raise RuntimeError(
                (
                    "编辑后校验失败："
                    "磁盘内容与期望的编辑结果不一致。"
                )
            )

        # =====================================================
        # Post-Write Syntax Validation
        # =====================================================

        syntax_validated = (
            cls.validate_candidate(
                file_path,
                actual_content,
            )
        )

        before_hash = None

        if (
            before_content
            is not None
        ):

            before_hash = (
                cls.content_hash(
                    before_content
                )
            )

        after_hash = (
            cls.content_hash(
                actual_content
            )
        )

        changed = (
            before_content
            is None
            or before_content
            != actual_content
        )

        return EditVerification(
            changed=changed,
            content_verified=True,
            syntax_validated=(
                syntax_validated
            ),
            before_sha256=(
                before_hash
            ),
            after_sha256=(
                after_hash
            ),
        )
