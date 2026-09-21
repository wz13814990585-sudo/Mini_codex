"""Harness-generated final reports for coding tasks."""

from __future__ import annotations

from ..validation import TaskOutcome
from ..observability.redaction import redact


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

        if outcome == TaskOutcome.ALREADY_SATISFIED:
            lines = ["当前任务要求已经满足，无需修改代码。"]
        else:
            lines = ["任务已成功完成。"]
        changed = self.changed_files(agent)
        if changed:
            lines.extend(["", "修改文件："])
            lines.extend(f"- {path}" for path in changed)

        validation_lines = self.validation_lines(agent)
        if validation_lines:
            lines.extend(["", "验证结果："])
            lines.extend(validation_lines)

        requirements = getattr(agent, "task_requirements", None)
        if requirements is not None and requirements.items:
            satisfied = set(getattr(agent, "satisfied_requirement_ids", lambda: ())())
            lines.extend(["", "需求完成情况："])
            lines.extend(
                f"- [{'x' if item.id in satisfied else ' '}] {item.description}"
                for item in requirements.items
            )

        if debug:
            lines.extend(["", "结果：", f"{outcome.name} ({outcome.value})"])
        return "\n".join(lines)

    def blocked(self, reason: str, *, debug: bool = False) -> str:
        concrete = str(redact(str(reason or "确定性阻塞导致无法完成。"))).strip()
        lines = ["任务被阻塞。", "", "原因：", f"- {concrete}"]
        if debug:
            lines.extend(["", "结果：", "BLOCKED"])
        return "\n".join(lines)

    def incomplete(self, agent, reason: str, *, debug: bool = False) -> str:
        lines = [
            "任务未完成。",
            "",
            "原因：",
            f"- {str(redact(str(reason or '缺少所需的完成证据。'))).strip()}",
        ]
        changed = self.changed_files(agent)
        if changed:
            lines.extend(["", "停止前已修改："])
            lines.extend(f"- {path}" for path in changed)
        requirements = getattr(agent, "task_requirements", None)
        if requirements is not None and requirements.items:
            satisfied = set(getattr(agent, "satisfied_requirement_ids", lambda: ())())
            missing = [item for item in requirements.items if item.id not in satisfied]
        else:
            missing = []
        if missing:
            lines.extend(["", "尚缺少以下需求证据："])
            lines.extend(f"- {item.description}" for item in missing)
        if debug:
            lines.extend(["", "结果：", "INCOMPLETE"])
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
            lines.append("- 针对性验收验证：通过")
        if state.targeted_passed:
            lines.append("- 相关回归验证：通过")
        if state.full_passed:
            lines.append("- 全量回归验证：通过")
        return lines
