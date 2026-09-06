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

    status: ValidationStatus

    previous_failed: int | None = None

    current_failed: int | None = None

    previous_revision: int | None = None

    current_revision: int | None = None

    validation_key: str | None = None

    message: str | None = None

    stalled: bool = False

    @property
    def meaningful_progress(
        self,
    ) -> bool:

        return (
            self.status
            in {
                ValidationStatus.PASSED,
                ValidationStatus.IMPROVED,
            }
        )

    @property
    def crossed_revision(
        self,
    ) -> bool:

        return bool(
            self.previous_revision
            is not None
            and self.current_revision
            is not None
            and self.current_revision
            > self.previous_revision
        )


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

        # =====================================================
        # Duplicate Tool State
        # =====================================================

        self.last_tool_signature = None

        self.same_tool_repeat_count = 0

        # Counts survive interleaved calls until real progress
        # resets this controller.
        self._tool_signature_counts: dict[
            tuple[str, str], int
        ] = {}

        self.inspection_streak = 0

        # =====================================================
        # Action History
        # =====================================================

        self.recent_actions: list[
            str
        ] = []

        # =====================================================
        # Last Observed Validation
        #
        # Kept for human-readable summaries.
        # =====================================================

        self.last_validation_failed_count: (
            int | None
        ) = None

        self.last_validation_key: (
            str | None
        ) = None

        self.last_validation_revision: (
            int | None
        ) = None

        self.validation_no_progress_count = 0

        # =====================================================
        # Comparable Validation Series
        #
        # key -> (failed_count, edit_revision)
        # =====================================================

        self._validation_series: dict[
            str,
            tuple[
                int,
                int | None,
            ],
        ] = {}

    # =========================================================
    # Reset
    # =========================================================

    def reset(
        self,
        new_task: bool = False,
    ) -> None:

        self.last_tool_signature = None

        self.same_tool_repeat_count = 0

        self._tool_signature_counts.clear()

        self.inspection_streak = 0

        self.recent_actions.clear()

        self.last_validation_failed_count = None

        self.last_validation_key = None

        self.last_validation_revision = None

        self.validation_no_progress_count = 0

        self._validation_series.clear()

    def mark_meaningful_progress(
        self,
    ) -> None:
        """Start a fresh action phase without losing validation history."""

        self.last_tool_signature = None
        self.same_tool_repeat_count = 0
        self._tool_signature_counts.clear()
        self.inspection_streak = 0
        self.recent_actions.clear()

    # =========================================================
    # Duplicate Tool Detection
    # =========================================================

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

        signature_count = (
            self._tool_signature_counts.get(
                signature,
                0,
            )
            + 1
        )

        self._tool_signature_counts[
            signature
        ] = signature_count

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
            signature_count
            > self.max_same_tool_repeats
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

    # =========================================================
    # Record Action
    # =========================================================

    def record_action(
        self,
        tool_name: str,
    ) -> None:

        self.recent_actions.append(
            tool_name
        )

        inspection_tools = {
            "read_file",
            "search_code",
            "search_symbol",
            "list_files",
            "git_status",
            "git_diff",
        }

        if tool_name in inspection_tools:
            self.inspection_streak += 1
        else:
            self.inspection_streak = 0

        self.recent_actions = (
            self.recent_actions[
                -self.progress_window:
            ]
        )

    def consume_inspection_nudge(
        self,
    ) -> bool:
        """Return true once after inspection-only drift."""

        if self.inspection_streak < self.progress_window:
            return False

        self.inspection_streak = 0

        return True

    # =========================================================
    # Action Stall Detection
    # =========================================================

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

    # =========================================================
    # Validation Progress
    # =========================================================

    def track_validation(
        self,
        failed_count: int | None,
        validation_key: str | None = None,
        edit_revision: int | None = None,
    ) -> ValidationProgress:

        # =====================================================
        # Cannot Interpret
        # =====================================================

        if (
            failed_count
            is None
        ):

            return ValidationProgress(
                status=(
                    ValidationStatus.UNKNOWN
                ),
                current_revision=(
                    edit_revision
                ),
                validation_key=(
                    validation_key
                ),
            )

        normalized_key = (
            validation_key
            or "__unknown_validation__"
        )

        # =====================================================
        # Human-readable Latest State
        # =====================================================

        self.last_validation_failed_count = (
            failed_count
        )

        self.last_validation_key = (
            validation_key
        )

        self.last_validation_revision = (
            edit_revision
        )

        previous = (
            self._validation_series
            .get(
                normalized_key
            )
        )

        # Always record this observation for the next
        # comparable validation.
        self._validation_series[
            normalized_key
        ] = (
            failed_count,
            edit_revision,
        )

        # =====================================================
        # First Observation Of This Series
        # =====================================================

        if (
            previous
            is None
        ):

            self.validation_no_progress_count = 0

            if (
                failed_count
                == 0
            ):

                return ValidationProgress(
                    status=(
                        ValidationStatus.PASSED
                    ),
                    previous_failed=None,
                    current_failed=0,
                    previous_revision=None,
                    current_revision=(
                        edit_revision
                    ),
                    validation_key=(
                        validation_key
                    ),
                    message=(
                        "Validation succeeded."
                    ),
                )

            return ValidationProgress(
                status=(
                    ValidationStatus.UNKNOWN
                ),
                previous_failed=None,
                current_failed=(
                    failed_count
                ),
                previous_revision=None,
                current_revision=(
                    edit_revision
                ),
                validation_key=(
                    validation_key
                ),
                message=(
                    "Initial comparable validation "
                    f"recorded: {failed_count} failed."
                ),
            )

        (
            previous_failed,
            previous_revision,
        ) = previous

        # =====================================================
        # Passed
        # =====================================================

        if (
            failed_count
            == 0
        ):

            self.validation_no_progress_count = 0

            return ValidationProgress(
                status=(
                    ValidationStatus.PASSED
                ),
                previous_failed=(
                    previous_failed
                ),
                current_failed=0,
                previous_revision=(
                    previous_revision
                ),
                current_revision=(
                    edit_revision
                ),
                validation_key=(
                    validation_key
                ),
                message=(
                    "Validation succeeded."
                ),
            )

        # =====================================================
        # Improved
        # =====================================================

        if (
            failed_count
            < previous_failed
        ):

            self.validation_no_progress_count = 0

            return ValidationProgress(
                status=(
                    ValidationStatus.IMPROVED
                ),
                previous_failed=(
                    previous_failed
                ),
                current_failed=(
                    failed_count
                ),
                previous_revision=(
                    previous_revision
                ),
                current_revision=(
                    edit_revision
                ),
                validation_key=(
                    validation_key
                ),
                message=(
                    "Validation improved: "
                    f"{previous_failed} failed -> "
                    f"{failed_count} failed."
                ),
            )

        # =====================================================
        # Unchanged
        # =====================================================

        if (
            failed_count
            == previous_failed
        ):

            self.validation_no_progress_count += 1

            stalled = (
                self.validation_no_progress_count
                >= self.max_validation_no_progress
            )

            return ValidationProgress(
                status=(
                    ValidationStatus.UNCHANGED
                ),
                previous_failed=(
                    previous_failed
                ),
                current_failed=(
                    failed_count
                ),
                previous_revision=(
                    previous_revision
                ),
                current_revision=(
                    edit_revision
                ),
                validation_key=(
                    validation_key
                ),
                message=(
                    "Validation unchanged: "
                    f"{failed_count} tests "
                    "still failing."
                ),
                stalled=(
                    stalled
                ),
            )

        # =====================================================
        # Regressed
        # =====================================================

        self.validation_no_progress_count += 1

        stalled = (
            self.validation_no_progress_count
            >= self.max_validation_no_progress
        )

        return ValidationProgress(
            status=(
                ValidationStatus.REGRESSED
            ),
            previous_failed=(
                previous_failed
            ),
            current_failed=(
                failed_count
            ),
            previous_revision=(
                previous_revision
            ),
            current_revision=(
                edit_revision
            ),
            validation_key=(
                validation_key
            ),
            message=(
                "Validation regressed: "
                f"{previous_failed} failed -> "
                f"{failed_count} failed."
            ),
            stalled=(
                stalled
            ),
        )
