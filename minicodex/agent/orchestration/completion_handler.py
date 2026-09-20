"""Unified final-response and deterministic completion handling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..validation import TaskOutcome
from .orchestration_transitions import completion_transition, record_task_outcome
from .task_report import TaskReportBuilder
from ..reason_codes import ReasonCode
from ..routing import TaskIntent


class FinalResponseMode(str, Enum):
    INFORMATIONAL_ANSWER = "informational_answer"
    INSPECTION_REPORT = "inspection_report"
    TASK_REPORT = "task_report"


@dataclass(frozen=True)
class CompletionHandleResult:
    finished: bool
    output: str | None = None
    followup_instruction: str | None = None


class CompletionHandler:
    """Make all loop exits obey the same product completion semantics."""

    EXECUTION_CORRECTION = (
        "这是编码任务。不要解释如何完成，请使用可用工具执行所请求的修改并验证结果。"
    )

    def __init__(self, report_builder: TaskReportBuilder | None = None) -> None:
        self.report_builder = report_builder or TaskReportBuilder()
        self.reset()

    def reset(self) -> None:
        self.execution_correction_issued = False

    @staticmethod
    def response_mode(agent) -> FinalResponseMode:
        route = getattr(agent, "execution_route", None)
        intent = getattr(route, "intent", TaskIntent.MODIFY)
        if intent == TaskIntent.INFORMATIONAL:
            return FinalResponseMode.INFORMATIONAL_ANSWER
        if intent == TaskIntent.INSPECT_ONLY:
            return FinalResponseMode.INSPECTION_REPORT
        return FinalResponseMode.TASK_REPORT

    def handle_text_response(
        self,
        agent,
        *,
        content: str,
        remaining_steps: int,
    ) -> CompletionHandleResult:
        response_mode = self.response_mode(agent)
        if response_mode == FinalResponseMode.INFORMATIONAL_ANSWER:
            if getattr(agent.validation_pipeline.state, "has_edit", False):
                return self.handle_incomplete(
                    agent, reason="信息类任务在工作区发生编辑后不能视为完成。"
                )
            record_task_outcome(
                agent,
                TaskOutcome.INFORMATIONAL_ANSWER,
                "该请求被分类为信息查询。",
            )
            return CompletionHandleResult(True, content)
        if response_mode == FinalResponseMode.INSPECTION_REPORT:
            route = getattr(agent, "execution_route", None)
            metrics = getattr(agent, "execution_metrics", None)
            needs_repo_inspection = True
            inspected = bool(getattr(metrics, "inspection_tool_count", 0))
            if getattr(agent.validation_pipeline.state, "has_edit", False):
                return self.handle_incomplete(
                    agent, reason="仅探查授权被工作区编辑违反。"
                )
            if needs_repo_inspection and not inspected and remaining_steps > 0:
                return CompletionHandleResult(
                    False,
                    followup_instruction=(
                        "请先用读取/搜索工具探查所请求的仓库目标，"
                        "再报告发现；不要修改文件。"
                    ),
                )
            record_task_outcome(
                agent,
                TaskOutcome.INSPECTED,
                "仅探查请求已在不修改工作区的情况下完成答复。",
            )
            return CompletionHandleResult(True, content)

        self._reconcile_plan(agent)
        transition = completion_transition(agent)
        if transition.can_finish:
            return self._successful(agent, transition.decision)

        blocker = self._concrete_blocker(agent, content)
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

    def handle_incomplete(self, agent, *, reason: str) -> CompletionHandleResult:
        record_task_outcome(agent, TaskOutcome.INCOMPLETE, reason)
        return CompletionHandleResult(
            True,
            self.report_builder.build(agent, outcome=TaskOutcome.INCOMPLETE, reason=reason),
        )

    def handle_control_stop(
        self,
        agent,
        *,
        reason: str,
        reason_code: ReasonCode | None = None,
    ) -> CompletionHandleResult:
        outcome = TaskOutcome.BLOCKED if reason_code == ReasonCode.BLOCKED else TaskOutcome.INCOMPLETE
        record_task_outcome(agent, outcome, reason, reason_code)
        return CompletionHandleResult(
            True,
            self.report_builder.build(agent, outcome=outcome, reason=reason),
        )

    def finish_ready(self, agent, decision) -> CompletionHandleResult:
        return self._successful(agent, decision)

    def _successful(self, agent, decision) -> CompletionHandleResult:
        record_task_outcome(agent, decision.outcome, decision.reason)
        return CompletionHandleResult(
            True,
            self.report_builder.build(agent, outcome=decision.outcome, reason=decision.reason),
        )

    @staticmethod
    def _reconcile_plan(agent) -> None:
        """Reconcile criteria, then supersede bookkeeping-only remainder."""

        if getattr(agent, "active_plan", None) is None:
            return
        reconcile = getattr(agent, "reconcile_plan_progress", None)
        if callable(reconcile):
            reconcile()
        policy = getattr(agent, "completion_policy", None)
        decision = policy.evaluate(agent) if policy is not None else None
        plan = getattr(agent, "active_plan", None)
        if decision is None or not decision.can_complete or plan is None or plan.is_completed():
            return
        supersede = getattr(plan, "supersede_remaining", None)
        if callable(supersede):
            superseded = supersede()
            if superseded:
                agent.plan_version += 1
                sync = getattr(agent, "sync_plan_state", None)
                if callable(sync):
                    sync(superseded_steps=superseded)

    @staticmethod
    def _concrete_blocker(agent, content: str) -> str | None:
        text = str(content or "").strip()
        if not text.upper().startswith("BLOCKED:"):
            return None
        reason = text.split(":", 1)[1].strip()
        generic = {
            "",
            "blocked",
            "cannot do this",
            "i cannot do this",
            "unable to proceed",
            "无法继续",
            "无法进行",
            "做不到",
            "我做不到",
            "不能完成",
        }
        if len(reason) < 8 or reason.casefold() in generic:
            return None
        evidence = tuple(getattr(agent, "concrete_blockers", ()) or ())
        if not evidence:
            return None
        return reason

    @staticmethod
    def _missing_evidence_instruction(status: str) -> str:
        if status == "needs_acceptance":
            return "请继续编码任务，并获取针对性验收证据。"
        if status == "needs_relevant_validation":
            return "请运行当前变更所需的相关回归验证。"
        if status == "needs_full_validation":
            return "停止前请运行所需的全量回归验证。"
        return "请用具体工具动作继续编码任务；任务尚未完成。"
