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
                        "自动重新规划成功。"
                        "请按修订后的计划继续。"
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
                or "未知的重新规划失败。"
            )

            return (
                (
                    "自动重新规划失败："
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
            "在策略恢复与重新规划之后，Agent 仍停滞不前。"
        )

    def _strategy_warning(
        self,
        reason: str,
    ) -> str:

        return (
            "【恢复策略警告】\n"
            "当前做法没有带来有意义的进展。\n"
            f"原因：{reason}\n\n"
            "不要重复同一策略。"
            "请选择实质不同的下一步动作。"
            "若已有足够证据表明存在代码缺陷，"
            "请做针对性修改。"
            "若计划建立在错误假设上，"
            "请调用 replan。"
        )
