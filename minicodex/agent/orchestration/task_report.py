"""Harness-generated final reports for coding tasks."""

from __future__ import annotations

from ..completion import TaskOutcome


class TaskReportBuilder:
    """Build concise user-facing reports without control-plane diagnostics."""

    def build(
        self,
        agent,
        *,
        outcome: TaskOutcome,
        reason: str = "",
    ) -> str:
        if outcome == TaskOutcome.BLOCKED:
            return self.blocked(reason)
        if outcome == TaskOutcome.INCOMPLETE:
            return self.incomplete(agent, reason)

        lines = [
            (
                "Task already satisfied."
                if outcome == TaskOutcome.ALREADY_SATISFIED
                else "Task completed successfully."
            )
        ]
        changed = self.changed_files(agent)
        if changed:
            lines.extend(["", "Changed:"])
            lines.extend(f"- {path}" for path in changed)
        elif outcome == TaskOutcome.ALREADY_SATISFIED:
            lines.extend(["", "No workspace changes were required."])

        validation_lines = self.validation_lines(agent)
        if validation_lines:
            lines.extend(["", "Validation:"])
            lines.extend(validation_lines)

        # The enum value is retained as a stable machine-readable token while
        # the upper-case name remains easy to scan in terminal output.
        lines.extend(["", "Outcome:", f"{outcome.name} ({outcome.value})"])
        return "\n".join(lines)

    def blocked(self, reason: str) -> str:
        concrete = str(reason or "A deterministic blocker prevented completion.").strip()
        return "\n".join(
            ["Task blocked.", "", "Reason:", f"- {concrete}", "", "Outcome:", "BLOCKED"]
        )

    def incomplete(self, agent, reason: str) -> str:
        lines = [
            "Task incomplete.",
            "",
            "Reason:",
            f"- {str(reason or 'Required completion evidence is missing.').strip()}",
        ]
        changed = self.changed_files(agent)
        if changed:
            lines.extend(["", "Changed before stopping:"])
            lines.extend(f"- {path}" for path in changed)
        lines.extend(["", "Outcome:", "INCOMPLETE"])
        return "\n".join(lines)

    @staticmethod
    def changed_files(agent) -> tuple[str, ...]:
        awareness = getattr(agent, "git_awareness", None)
        if awareness is None:
            return ()
        try:
            return tuple(awareness.task_state().agent_touched_files)
        except Exception:
            return ()

    @staticmethod
    def validation_lines(agent) -> list[str]:
        pipeline = getattr(agent, "validation_pipeline", None)
        if pipeline is None:
            return []
        state = pipeline.state
        lines: list[str] = []
        if state.acceptance_passed:
            lines.append("- targeted acceptance: passed")
        if state.targeted_passed:
            lines.append("- relevant regression: passed")
        if state.full_passed:
            lines.append("- full regression: passed")
        return lines
