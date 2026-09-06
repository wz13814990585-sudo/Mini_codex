from dataclasses import (
    dataclass,
    field,
)

from .working_memory import (
    WorkingMemory,
)


@dataclass
class WorkingSummary:
    """
    Compact task-level factual execution history.

    Stage 5 responsibility:

        preserve recent factual execution events

    Stage 15 WorkingMemory responsibility:

        preserve latest-known structured task state

    Both are task-local and reset for every new user task.
    """

    max_items: int = 30

    items: list[str] = field(
        default_factory=list
    )

    memory: WorkingMemory = field(
        default_factory=WorkingMemory,
        repr=False,
    )

    # =========================================================
    # Reset
    # =========================================================

    def reset(
        self,
    ) -> None:

        self.items.clear()

        self.memory.reset()

    # =========================================================
    # Add Fact
    # =========================================================

    def add(
        self,
        text: str,
    ) -> None:

        normalized = (
            str(
                text
            )
            .strip()
        )

        if not normalized:

            return

        # Avoid exact duplicate facts.
        if (
            normalized
            in self.items
        ):

            return

        self.items.append(
            normalized
        )

        # Keep summary bounded.
        if (
            len(
                self.items
            )
            > self.max_items
        ):

            overflow = (
                len(
                    self.items
                )
                - self.max_items
            )

            del self.items[
                :overflow
            ]

    # =========================================================
    # Record Tool Result
    # =========================================================

    def record_tool_result(
        self,
        tool_name: str,
        arguments: dict,
        result,
    ) -> None:

        if not isinstance(
            arguments,
            dict,
        ):

            arguments = {}

        # =====================================================
        # Stage 15 Structured Working Memory
        #
        # Memory is a cache, not source of truth.
        #
        # A memory-recording failure must never break the Agent
        # execution path.
        # =====================================================

        try:

            self.memory.record_tool_result(
                tool_name=(
                    tool_name
                ),
                arguments=(
                    arguments
                ),
                result=(
                    result
                ),
            )

        except Exception:

            pass

        path = (
            str(
                arguments.get(
                    "path",
                    "",
                )
                or ""
            )
            .strip()
        )

        # =====================================================
        # Read File
        # =====================================================

        if (
            tool_name
            == "read_file"
        ):

            if result.success:

                if path:

                    self.add(
                        f"Inspected file: "
                        f"{path}."
                    )

                else:

                    self.add(
                        "A file was inspected "
                        "successfully."
                    )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        path,
                        result,
                    )
                )

            return

        # =====================================================
        # Search Code
        # =====================================================

        if (
            tool_name
            == "search_code"
        ):

            query = (
                str(
                    arguments.get(
                        "query",
                        "",
                    )
                    or ""
                )
                .strip()
            )

            if result.success:

                if query:

                    self.add(
                        "Searched project code for: "
                        f"{query}."
                    )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        query,
                        result,
                    )
                )

            return

        # =====================================================
        # Search Symbol
        # =====================================================

        if (
            tool_name
            == "search_symbol"
        ):

            query = (
                str(
                    arguments.get(
                        "query",
                        arguments.get(
                            "name",
                            "",
                        ),
                    )
                    or ""
                )
                .strip()
            )

            if result.success:

                if query:

                    self.add(
                        "Searched project symbols for: "
                        f"{query}."
                    )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        query,
                        result,
                    )
                )

            return

        # =====================================================
        # Edit Tools
        # =====================================================

        if (
            tool_name
            in {
                "write_file",
                "patch_file",
                "replace_lines",
                "replace_symbol",
            }
        ):

            if result.success:

                if path:

                    self.add(
                        "Modified file successfully: "
                        f"{path}."
                    )

                else:

                    self.add(
                        "A project file was modified "
                        "successfully."
                    )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        path,
                        result,
                    )
                )

            return

        # =====================================================
        # Tests
        # =====================================================

        if (
            tool_name
            == "run_tests"
        ):

            if not result.success:

                self.add(
                    self._failure_fact(
                        tool_name,
                        path,
                        result,
                    )
                )

                return

            tests_passed = (
                result.data.get(
                    "tests_passed"
                )
            )

            passed = (
                self._safe_int(
                    result.data.get(
                        "passed",
                        0,
                    )
                )
            )

            failed = (
                self._safe_int(
                    result.data.get(
                        "failed",
                        0,
                    )
                )
            )

            errors = (
                self._safe_int(
                    result.data.get(
                        "errors",
                        0,
                    )
                )
            )

            if (
                tests_passed
                is True
            ):

                self.add(
                    "Validation passed: "
                    f"{passed} tests passed, "
                    "0 failures."
                )

            elif (
                failed
                + errors
                > 0
            ):

                self.add(
                    "Validation still failing: "
                    f"{passed} passed, "
                    f"{failed} failed, "
                    f"{errors} errors."
                )

            else:

                self.add(
                    "Validation ran, but no "
                    "definitive pass/fail result "
                    "was available."
                )

            return

        # =====================================================
        # Run Command
        # =====================================================

        if (
            tool_name
            == "run_command"
        ):

            command = (
                str(
                    arguments.get(
                        "command",
                        "",
                    )
                    or ""
                )
                .strip()
            )

            command_succeeded = (
                result.data.get(
                    "command_succeeded"
                )
            )

            if (
                result.success
                and command_succeeded
                is True
            ):

                self.add(
                    "Command succeeded: "
                    f"{command}."
                )

            elif (
                result.success
                and command_succeeded
                is False
            ):

                self.add(
                    "Command completed "
                    "unsuccessfully: "
                    f"{command}."
                )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        command,
                        result,
                    )
                )

            return

        # =====================================================
        # Complete Plan Step
        # =====================================================

        if (
            tool_name
            == "complete_plan_step"
        ):

            if (
                result.data.get(
                    "completed"
                )
            ):

                step_id = (
                    result.data.get(
                        "step_id"
                    )
                )

                description = (
                    result.data.get(
                        "step_description"
                    )
                )

                self.add(
                    "Completed plan step "
                    f"{step_id}: "
                    f"{description}."
                )

            return

        # =====================================================
        # Replan
        # =====================================================

        if (
            tool_name
            == "replan"
        ):

            if (
                result.data.get(
                    "replanned"
                )
            ):

                reason = (
                    str(
                        result.data.get(
                            "reason",
                            "",
                        )
                        or ""
                    )
                    .strip()
                )

                if reason:

                    self.add(
                        "Implementation plan "
                        "was revised. "
                        f"Reason: {reason}"
                    )

                else:

                    self.add(
                        "Implementation plan "
                        "was revised."
                    )

            return

        # =====================================================
        # Git Status
        # =====================================================

        if (
            tool_name
            == "git_status"
        ):

            if result.success:

                self.add(
                    "Git repository state "
                    "was refreshed."
                )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        path,
                        result,
                    )
                )

            return

        # =====================================================
        # Git Diff
        # =====================================================

        if (
            tool_name
            == "git_diff"
        ):

            if result.success:

                if path:

                    self.add(
                        "Inspected Git diff for: "
                        f"{path}."
                    )

                else:

                    self.add(
                        "Inspected current Git diff."
                    )

            else:

                self.add(
                    self._failure_fact(
                        tool_name,
                        path,
                        result,
                    )
                )

            return

        # =====================================================
        # Generic Failure
        # =====================================================

        if not result.success:

            self.add(
                self._failure_fact(
                    tool_name,
                    path,
                    result,
                )
            )

    # =========================================================
    # Render
    # =========================================================

    def render(
        self,
    ) -> str:

        if (
            not self.items
            and len(
                self.memory
            )
            == 0
        ):

            # Preserve Stage 5 compatibility.
            return (
                "No important execution facts "
                "have been recorded yet."
            )

        sections = []

        # =====================================================
        # Stage 15 Current-State Memory
        # =====================================================

        if (
            len(
                self.memory
            )
            > 0
        ):

            sections.append(
                (
                    "Structured working memory "
                    "(latest known task state):\n"
                    f"{self.memory.render()}"
                )
            )

        # =====================================================
        # Stage 5 Recent History
        # =====================================================

        if self.items:

            recent_items = (
                self.items[
                    -10:
                ]
            )

            sections.append(
                (
                    "Recent execution facts:\n"
                    + "\n".join(
                        f"- {item}"
                        for item
                        in recent_items
                    )
                )
            )

        return "\n\n".join(
            sections
        )

    # =========================================================
    # Failure Helper
    # =========================================================

    def _failure_fact(
        self,
        tool_name: str,
        target: str,
        result,
    ) -> str:

        target_text = (
            f" ({target})"
            if target
            else ""
        )

        error = (
            str(
                getattr(
                    result,
                    "error",
                    "",
                )
                or ""
            )
            .strip()
        )

        if error:

            return (
                f"{tool_name}"
                f"{target_text} failed: "
                f"{error}"
            )

        return (
            f"{tool_name}"
            f"{target_text} failed."
        )

    # =========================================================
    # Safe Int
    # =========================================================

    @staticmethod
    def _safe_int(
        value,
    ) -> int:

        try:

            return int(
                value
                or 0
            )

        except (
            TypeError,
            ValueError,
        ):

            return 0