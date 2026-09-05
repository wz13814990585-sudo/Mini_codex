import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path


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
                "Edit would not change the file."
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

            raise ValueError(
                (
                    "Edit would produce invalid "
                    "Python syntax: "
                    f"{e.msg} "
                    f"(line {e.lineno}, "
                    f"column {e.offset})."
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
                    "Post-edit verification failed: "
                    "file does not exist after write."
                )
            )

        if not file_path.is_file():

            raise RuntimeError(
                (
                    "Post-edit verification failed: "
                    "path is not a file after write."
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
                    "Post-edit verification failed: "
                    "content on disk does not match "
                    "the expected edited content."
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