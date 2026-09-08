"""Unified final-response and deterministic completion handling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..completion import TaskOutcome
from .orchestration_transitions import completion_transition, record_task_outcome
from .task_report import TaskReportBuilder
from ..reason_codes import ReasonCode


class FinalResponseMode(str, Enum):
    INFORMATIONAL_ANSWER = "informational_answer"
    TASK_REPORT = "task_report"


@dataclass(frozen=True)
class CompletionHandleResult:
    finished: bool
    output: str | None = None
    followup_instruction: str | None = None


class CompletionHandler:
    """Make all loop exits obey the same product completion semantics."""

    EXECUTION_CORRECTION = (
        "This is a coding task. Do not explain how to do it. Use the available "
        "tools to perform the requested change and validate it."
    )

    def __init__(self, report_builder: TaskReportBuilder | None = None) -> None:
        self.report_builder = report_builder or TaskReportBuilder()
        self.reset()

    def reset(self) -> None:
        self.execution_correction_issued = False

    @staticmethod
    def response_mode(agent) -> FinalResponseMode:
        route = getattr(agent, "execution_route", None)
        return (
            FinalResponseMode.TASK_REPORT
            if bool(getattr(route, "requires_coding_action", True))
            else FinalResponseMode.INFORMATIONAL_ANSWER
        )

    def handle_text_response(
        self,
        agent,
        *,
        content: str,
        remaining_steps: int,
    ) -> CompletionHandleResult:
        if self.response_mode(agent) == FinalResponseMode.INFORMATIONAL_ANSWER:
            record_task_outcome(
                agent,
                TaskOutcome.INFORMATIONAL_ANSWER,
                "The request was classified as informational.",
            )
            return CompletionHandleResult(True, content)

        self._reconcile_plan(agent)
        transition = completion_transition(agent)
        if transition.can_finish:
            return self._successful(agent, transition.decision)

        blocker = self._concrete_blocker(content)
        if blocker is not None:
            record_task_outcome(agent, TaskOutcome.BLOCKED, blocker, ReasonCode.BLOCKED)
            return CompletionHandleResult(
                True,
                self.report_builder.build(
                    agent,
                    outcome=TaskOutcome.BLOCKED,
                    reason=blocker,
                ),
            )

        if remaining_steps > 0:
            if not self.execution_correction_issued:
                self.execution_correction_issued = True
                instruction = self.EXECUTION_CORRECTION
            else:
                instruction = self._missing_evidence_instruction(transition.decision.status.value)
            return CompletionHandleResult(False, followup_instruction=instruction)

        return self.handle_budget_exhausted(
            agent,
            reason=transition.decision.reason,
        )

    def check_after_batch(self, agent) -> CompletionHandleResult:
        self._reconcile_plan(agent)
        transition = completion_transition(agent)
        if transition.can_finish:
            return self._successful(agent, transition.decision)
        return CompletionHandleResult(False)

    def handle_budget_exhausted(self, agent, *, reason: str) -> CompletionHandleResult:
        self._reconcile_plan(agent)
        transition = completion_transition(agent)
        if transition.can_finish:
            return self._successful(agent, transition.decision)
        metrics = getattr(agent, "execution_metrics", None)
        if metrics is not None:
            metrics.max_steps_exhausted = True
        record_task_outcome(agent, TaskOutcome.INCOMPLETE, reason, ReasonCode.MAX_STEPS)
        return CompletionHandleResult(
            True,
            self.report_builder.build(
                agent,
                outcome=TaskOutcome.INCOMPLETE,
                reason=reason,
            ),
        )

    def build_task_report(self, agent, *, outcome: TaskOutcome, reason: str = "") -> str:
        return self.report_builder.build(agent, outcome=outcome, reason=reason)

    def _successful(self, agent, decision) -> CompletionHandleResult:
        record_task_outcome(agent, decision.outcome, decision.reason)
        return CompletionHandleResult(
            True,
            self.report_builder.build(agent, outcome=decision.outcome, reason=decision.reason),
        )

    @staticmethod
    def _reconcile_plan(agent) -> None:
        """Give deterministic criteria one final chance before any exit."""

        if getattr(agent, "active_plan", None) is None:
            return
        reconcile = getattr(agent, "reconcile_plan_progress", None)
        if callable(reconcile):
            reconcile()

    @staticmethod
    def _concrete_blocker(content: str) -> str | None:
        text = str(content or "").strip()
        if not text.upper().startswith("BLOCKED:"):
            return None
        reason = text.split(":", 1)[1].strip()
        generic = {
            "", "blocked", "cannot do this", "i cannot do this", "unable to proceed"
        }
        if len(reason) < 8 or reason.casefold() in generic:
            return None
        return reason

    @staticmethod
    def _missing_evidence_instruction(status: str) -> str:
        if status == "needs_acceptance":
            return "Continue the coding task and obtain targeted acceptance evidence."
        if status == "needs_relevant_validation":
            return "Run the relevant regression validation required for the current change."
        if status == "needs_full_validation":
            return "Run the required full regression validation before stopping."
        return "Continue the coding task with a concrete tool action; it is not complete yet."
