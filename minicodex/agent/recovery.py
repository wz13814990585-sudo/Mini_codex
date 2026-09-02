class RecoveryController:

    def __init__(
        self,
        max_recovery_level: int = 3
    ):
        self.level = 0
        self.max_recovery_level = (
            max_recovery_level
        )

    def reset(self) -> None:
        self.level = 0

    def mark_progress(self) -> None:
        self.level = 0

    def recover(
        self,
        reason: str,
        replan_callback
    ) -> tuple[str, bool]:

        # Level 1
        if self.level == 0:
            self.level = 1

            return (
                self._strategy_warning(
                    reason
                ),
                True
            )

        # Level 2
        if self.level == 1:
            self.level = 2

            replan_result = (
                replan_callback(
                    reason
                )
            )

            if replan_result.startswith(
                "Plan successfully revised"
            ):
                return (
                    (
                        "Automatic replanning succeeded. "
                        "Continue using the revised plan."
                    ),
                    True
                )

            return (
                (
                    "Automatic replanning failed: "
                    f"{replan_result}"
                ),
                False
            )

        # Level 3
        self.level = 3

        return (
            (
                "The agent remains stalled after "
                "strategy recovery and replanning."
            ),
            False
        )

    def _strategy_warning(
        self,
        reason: str
    ) -> str:

        return (
            "RECOVERY WARNING:\n"
            "The current approach is not making "
            "meaningful progress.\n"
            f"Reason: {reason}\n\n"
            "Do not repeat the same strategy. "
            "Choose a materially different next action. "
            "If sufficient evidence identifies a code defect, "
            "make a targeted modification. "
            "If the plan is based on an incorrect assumption, "
            "call replan."
        )