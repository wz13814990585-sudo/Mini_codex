import json
import re


class ProgressController:

    def __init__(
        self,
        max_same_tool_repeats: int = 2,
        progress_window: int = 6,
        max_validation_no_progress: int = 2
    ):
        self.max_same_tool_repeats = max_same_tool_repeats
        self.progress_window = progress_window
        self.max_validation_no_progress = (
            max_validation_no_progress
        )

        self.last_tool_signature = None
        self.same_tool_repeat_count = 0

        self.recent_actions: list[str] = []

        self.last_validation_failed_count = None
        self.validation_no_progress_count = 0

    def reset(self) -> None:
        self.last_tool_signature = None
        self.same_tool_repeat_count = 0

        self.recent_actions.clear()

        self.last_validation_failed_count = None
        self.validation_no_progress_count = 0

    def check_duplicate_tool_call(
        self,
        tool_name: str,
        arguments: dict
    ) -> tuple[bool, str | None]:

        signature = (
            tool_name,
            json.dumps(
                arguments,
                sort_keys=True,
                ensure_ascii=False
            )
        )

        if signature == self.last_tool_signature:
            self.same_tool_repeat_count += 1
        else:
            self.last_tool_signature = signature
            self.same_tool_repeat_count = 0

        if (
            self.same_tool_repeat_count
            >= self.max_same_tool_repeats
        ):
            return (
                False,
                "The same tool with the same arguments "
                "has been repeated without meaningful progress."
            )

        return True, None

    def record_action(
        self,
        tool_name: str
    ) -> None:

        self.recent_actions.append(
            tool_name
        )

        self.recent_actions = (
            self.recent_actions[
                -self.progress_window:
            ]
        )

    def is_action_stalled(self) -> bool:

        if (
            len(self.recent_actions)
            < self.progress_window
        ):
            return False

        recent = self.recent_actions[
            -self.progress_window:
        ]

        edit_tools = {
            "patch_file",
            "write_file"
        }

        validation_tools = {
            "run_tests",
            "run_command"
        }

        inspection_tools = {
            "read_file",
            "search_code",
            "list_files"
        }

        has_edit = any(
            action in edit_tools
            for action in recent
        )

        validation_count = sum(
            action in validation_tools
            for action in recent
        )

        inspection_count = sum(
            action in inspection_tools
            for action in recent
        )

        return (
            not has_edit
            and validation_count >= 2
            and inspection_count >= 2
        )

    def track_validation(
        self,
        result: str
    ) -> tuple[bool, str | None]:

        failed_count = (
            self._extract_failed_test_count(
                result
            )
        )

        if failed_count is None:
            return True, None

        if (
            self.last_validation_failed_count
            is None
        ):
            self.last_validation_failed_count = (
                failed_count
            )

            if failed_count == 0:
                return (
                    True,
                    "Validation succeeded."
                )

            return True, None

        previous = (
            self.last_validation_failed_count
        )

        if failed_count == 0:
            self.last_validation_failed_count = 0
            self.validation_no_progress_count = 0

            return (
                True,
                "Validation succeeded."
            )

        if failed_count < previous:
            self.last_validation_failed_count = (
                failed_count
            )
            self.validation_no_progress_count = 0

            return (
                True,
                (
                    "Validation improved: "
                    f"{previous} failed -> "
                    f"{failed_count} failed."
                )
            )

        self.validation_no_progress_count += 1

        self.last_validation_failed_count = (
            failed_count
        )

        if (
            self.validation_no_progress_count
            >= self.max_validation_no_progress
        ):
            return (
                False,
                (
                    "Validation is not improving. "
                    f"Current failed tests: "
                    f"{failed_count}."
                )
            )

        return True, None

    def _extract_failed_test_count(
        self,
        result: str
    ) -> int | None:

        patterns = [
            r"(\d+)\s+failed",
            r"failed=(\d+)"
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                result,
                re.IGNORECASE
            )

            if match:
                return int(
                    match.group(1)
                )

        if "Exit code: 0" in result:
            return 0

        return None
