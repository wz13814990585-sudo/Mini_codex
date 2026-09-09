"""Harness-generated final reports for coding tasks."""

from __future__ import annotations

from ..validation import TaskOutcome


class TaskReportBuilder:
    """Build concise user-facing reports without control-plane diagnostics."""

    def build(
        self,
        agent,
        *,
        outcome: TaskOutcome,
        reason: str = "",
    ) -> str:
        debug = str(getattr(getattr(agent, "output_level", "normal"), "value", getattr(agent, "output_level", "normal"))) == "debug"
        if outcome == TaskOutcome.BLOCKED:
            return self.blocked(reason, debug=debug)
        if outcome == TaskOutcome.INCOMPLETE:
            return self.incomplete(agent, reason, debug=debug)

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

        if debug:
            lines.extend(["", "Outcome:", f"{outcome.name} ({outcome.value})"])
        return "\n".join(lines)

    def blocked(self, reason: str, *, debug: bool = False) -> str:
        concrete = str(reason or "A deterministic blocker prevented completion.").strip()
        lines = ["Task blocked.", "", "Reason:", f"- {concrete}"]
        if debug:
            lines.extend(["", "Outcome:", "BLOCKED"])
        return "\n".join(lines)

    def incomplete(self, agent, reason: str, *, debug: bool = False) -> str:
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
        if debug:
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
