import json

from dataclasses import dataclass
from enum import Enum


class ValidationStatus(
    str,
    Enum,
):
    UNKNOWN = "unknown"
    PASSED = "passed"
    IMPROVED = "improved"
    UNCHANGED = "unchanged"
    REGRESSED = "regressed"


@dataclass
class ValidationProgress:
    """
    Tracks whether repeated validation attempts are
    improving, unchanged, or regressing.

    This is NOT the source of truth for whether the
    current edit revision is fully validated.

    That responsibility belongs to ValidationPipeline.
    """

    status: ValidationStatus

    previous_failed: int | None = None
    current_failed: int | None = None

    message: str | None = None

    stalled: bool = False

    @property
    def meaningful_progress(
        self,
    ) -> bool:

        return self.status in {
            ValidationStatus.PASSED,
            ValidationStatus.IMPROVED,
        }


class ProgressController:

    def __init__(
        self,
        max_same_tool_repeats: int = 2,
        progress_window: int = 6,
        max_validation_no_progress: int = 2,
    ):
        self.max_same_tool_repeats = (
            max_same_tool_repeats
        )

        self.progress_window = (
            progress_window
        )

        self.max_validation_no_progress = (
            max_validation_no_progress
        )

        # =========================================
        # Duplicate Tool State
        # =========================================

        self.last_tool_signature = None
        self.same_tool_repeat_count = 0

        # =========================================
        # Action History
        # =========================================

        self.recent_actions: list[str] = []

        # =========================================
        # Validation Trend State
        #
        # This state may intentionally survive
        # multiple edit revisions inside a task.
        #
        # Example:
        #
        # 5 failing
        # → edit
        # → 3 failing
        #
        # That is meaningful repair progress.
        # =========================================

        self.last_validation_failed_count: (
            int | None
        ) = None

        self.validation_no_progress_count = 0

    # =============================================
    # Reset
    # =============================================

    def reset(
        self,
        new_task: bool = False,
    ) -> None:

        self.last_tool_signature = None
        self.same_tool_repeat_count = 0

        self.recent_actions.clear()

        # A normal reset occurs when a plan step completes
        # or replanning happens.
        #
        # Validation trend is intentionally reset here
        # because the local strategy context changed.
        self.last_validation_failed_count = None

        self.validation_no_progress_count = 0

    # =============================================
    # Duplicate Tool Detection
    # =============================================

    def check_duplicate_tool_call(
        self,
        tool_name: str,
        arguments: dict,
    ) -> tuple[
        bool,
        str | None,
    ]:

        signature = (
            tool_name,
            json.dumps(
                arguments,
                sort_keys=True,
                ensure_ascii=False,
            ),
        )

        if (
            signature
            == self.last_tool_signature
        ):

            self.same_tool_repeat_count += 1

        else:

            self.last_tool_signature = (
                signature
            )

            self.same_tool_repeat_count = 0

        if (
            self.same_tool_repeat_count
            >= self.max_same_tool_repeats
        ):

            return (
                False,
                (
                    "The same tool with the same "
                    "arguments has been repeated "
                    "without meaningful progress."
                ),
            )

        return (
            True,
            None,
        )

    # =============================================
    # Action History
    # =============================================

    def record_action(
        self,
        tool_name: str,
    ) -> None:

        self.recent_actions.append(
            tool_name
        )

        self.recent_actions = (
            self.recent_actions[
                -self.progress_window:
            ]
        )

    # =============================================
    # Action Stall Detection
    # =============================================

    def is_action_stalled(
        self,
    ) -> bool:

        if (
            len(
                self.recent_actions
            )
            < self.progress_window
        ):

            return False

        recent = (
            self.recent_actions[
                -self.progress_window:
            ]
        )

        edit_tools = {
            "patch_file",
            "replace_lines",
            "replace_symbol",
            "write_file",
        }

        validation_tools = {
            "run_tests",
            "run_command",
        }

        inspection_tools = {
            "read_file",
            "search_code",
            "search_symbol",
            "list_files",
        }

        has_edit = any(
            action in edit_tools
            for action
            in recent
        )

        validation_count = sum(
            action in validation_tools
            for action
            in recent
        )

        inspection_count = sum(
            action in inspection_tools
            for action
            in recent
        )

        return (
            not has_edit
            and validation_count >= 2
            and inspection_count >= 2
        )

    # =============================================
    # Validation Progress
    # =============================================

    def track_validation(
        self,
        failed_count: int | None,
    ) -> ValidationProgress:

        # =========================================
        # Cannot Understand Validation Result
        # =========================================

        if failed_count is None:

            return ValidationProgress(
                status=(
                    ValidationStatus.UNKNOWN
                ),
                message=None,
            )

        previous = (
            self.last_validation_failed_count
        )

        # =========================================
        # First Validation
        # =========================================

        if previous is None:

            self.last_validation_failed_count = (
                failed_count
            )

            if failed_count == 0:

                self.validation_no_progress_count = 0

                return ValidationProgress(
                    status=(
                        ValidationStatus.PASSED
                    ),
                    previous_failed=None,
                    current_failed=0,
                    message=(
                        "Validation succeeded."
                    ),
                )

            return ValidationProgress(
                status=(
                    ValidationStatus.UNKNOWN
                ),
                previous_failed=None,
                current_failed=failed_count,
                message=(
                    "Initial validation recorded: "
                    f"{failed_count} failed."
                ),
            )

        # =========================================
        # Tests Passed
        # =========================================

        if failed_count == 0:

            self.last_validation_failed_count = 0

            self.validation_no_progress_count = 0

            return ValidationProgress(
                status=(
                    ValidationStatus.PASSED
                ),
                previous_failed=previous,
                current_failed=0,
                message=(
                    "Validation succeeded."
                ),
            )

        # =========================================
        # Validation Improved
        #
        # 5 failed -> 3 failed
        # =========================================

        if (
            failed_count
            < previous
        ):

            self.last_validation_failed_count = (
                failed_count
            )

            self.validation_no_progress_count = 0

            return ValidationProgress(
                status=(
                    ValidationStatus.IMPROVED
                ),
                previous_failed=previous,
                current_failed=failed_count,
                message=(
                    "Validation improved: "
                    f"{previous} failed -> "
                    f"{failed_count} failed."
                ),
            )

        # =========================================
        # Validation Unchanged
        #
        # 3 failed -> 3 failed
        # =========================================

        if (
            failed_count
            == previous
        ):

            self.validation_no_progress_count += 1

            self.last_validation_failed_count = (
                failed_count
            )

            stalled = (
                self.validation_no_progress_count
                >= self.max_validation_no_progress
            )

            return ValidationProgress(
                status=(
                    ValidationStatus.UNCHANGED
                ),
                previous_failed=previous,
                current_failed=failed_count,
                message=(
                    "Validation unchanged: "
                    f"{failed_count} tests "
                    "still failing."
                ),
                stalled=stalled,
            )

        # =========================================
        # Validation Regressed
        #
        # 2 failed -> 5 failed
        # =========================================

        self.validation_no_progress_count += 1

        self.last_validation_failed_count = (
            failed_count
        )

        stalled = (
            self.validation_no_progress_count
            >= self.max_validation_no_progress
        )

        return ValidationProgress(
            status=(
                ValidationStatus.REGRESSED
            ),
            previous_failed=previous,
            current_failed=failed_count,
            message=(
                "Validation regressed: "
                f"{previous} failed -> "
                f"{failed_count} failed."
            ),
            stalled=stalled,
        )