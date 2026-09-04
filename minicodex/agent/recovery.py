class RecoveryController:

    def __init__(
        self,
        max_recovery_level: int = 3,
    ):
        if not 1 <= max_recovery_level <= 3:
            raise ValueError(
                "max_recovery_level must be between 1 and 3."
            )

        self.level = 0
        self.max_recovery_level = max_recovery_level

    def reset(self) -> None:
        self.level = 0

    def mark_progress(self) -> None:
        self.level = 0

    def recover(
        self,
        reason: str,
        replan_callback,
    ) -> tuple[str, bool]:

        if self.level >= self.max_recovery_level:
            return self._stop_message(), False

        # =========================================
        # Level 1
        # Strategy warning
        # =========================================

        if self.level == 0:

            self.level = 1

            return (
                self._strategy_warning(
                    reason
                ),
                True,
            )

        # =========================================
        # Level 2
        # Automatic replanning
        # =========================================

        if self.level == 1:

            self.level = 2

            replan_result = (
                replan_callback(
                    reason
                )
            )

            replanned = bool(
                replan_result.get(
                    "replanned",
                    False,
                )
            )

            if replanned:
                return (
                    (
                        "Automatic replanning succeeded. "
                        "Continue using the revised plan."
                    ),
                    True,
                )

            failure_reason = (
                replan_result.get(
                    "failure_reason"
                )
                or replan_result.get(
                    "message"
                )
                or "Unknown replanning failure."
            )

            return (
                (
                    "Automatic replanning failed: "
                    f"{failure_reason}"
                ),
                False,
            )

        # =========================================
        # Level 3
        # Stop
        # =========================================

        self.level = 3

        return self._stop_message(), False

    def _stop_message(
        self,
    ) -> str:

        return (
            "The agent remains stalled after "
            "strategy recovery and replanning."
        )

    def _strategy_warning(
        self,
        reason: str,
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