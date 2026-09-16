"""Canonical runtime state and deterministic task transitions.

The filesystem and normalized tool results are factual inputs. ``TaskState``
is the single authoritative projection used by orchestration; controllers may
cache data, but report changes as ``RuntimeEvent`` objects rather than creating
a second version of task truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from .routing import ExecutionMode, TaskIntent
from .validation import TaskOutcome, ValidationOutcome


class AgentPhase(str, Enum):
    INSPECTING = "inspecting"
    ACTING = "acting"
    VALIDATING = "validating"
    FIXING = "fixing"
    FINALIZING = "finalizing"
    DONE = "done"
    BLOCKED = "blocked"


class RuntimeEventType(str, Enum):
    TASK_STARTED = "task_started"
    BUDGET_UPDATED = "budget_updated"
    CONTEXT_UPDATED = "context_updated"
    MODE_ESCALATED = "mode_escalated"
    PLAN_ACTIVATED = "plan_activated"
    PLAN_RECONCILED = "plan_reconciled"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    EDIT_APPLIED = "edit_applied"
    VALIDATION_OBSERVED = "validation_observed"
    REQUIREMENTS_UPDATED = "requirements_updated"
    RECOVERY_STARTED = "recovery_started"
    ROLLBACK_APPLIED = "rollback_applied"
    PHASE_CHANGED = "phase_changed"
    TASK_COMPLETED = "task_completed"
    TASK_BLOCKED = "task_blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True)
class RuntimeEvent:
    """One observable fact consumed by the reducer."""

    kind: RuntimeEventType
    data: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, kind: RuntimeEventType, **data: Any) -> "RuntimeEvent":
        return cls(kind=kind, data=MappingProxyType(dict(data)))


@dataclass
class TaskState:
    """Authoritative current state of one run."""

    run_id: str = ""
    mode: ExecutionMode | None = None
    intent: TaskIntent = TaskIntent.MODIFY
    needs_plan: bool = False
    planning_activated: bool = False
    phase: AgentPhase = AgentPhase.INSPECTING
    user_request: str = ""
    final_response_mode: str = "task_report"
    target_paths: tuple[str, ...] = ()
    relevant_paths: tuple[str, ...] = ()
    edit_revision: int = 0
    validation_revision: int = 0
    rollback_revision: int = 0
    plan_revision: int = 0
    completed_plan_steps: tuple[int, ...] = ()
    superseded_plan_steps: tuple[int, ...] = ()
    has_edit: bool = False
    acceptance_passed: bool = False
    relevant_validation_passed: bool = False
    full_validation_passed: bool = False
    consecutive_inspections: int = 0
    consecutive_no_state_change: int = 0
    consumed_steps: int = 0
    remaining_steps: int = 0
    outcome: TaskOutcome = TaskOutcome.INCOMPLETE
    latest_validation_outcome: ValidationOutcome | None = None
    active_evidence_edit_revision: int | None = None
    requirement_ids: tuple[str, ...] = ()
    satisfied_requirement_ids: tuple[str, ...] = ()
    latest_blocker: str | None = None
    recovery_level: int = 0
    active_tool: str | None = None
    event_sequence: int = 0

    @property
    def validation_version(self) -> int:
        return self.validation_revision

    @property
    def plan_version(self) -> int:
        return self.plan_revision

    def progress_key(self) -> tuple:
        return (
            self.edit_revision,
            self.completed_plan_steps,
            self.satisfied_requirement_ids,
            self.acceptance_passed,
            self.relevant_validation_passed,
            self.full_validation_passed,
        )

    def invariant_violations(
        self, *, tool_batch_open: bool = False, next_provider_call: bool = False
    ) -> tuple[str, ...]:
        problems = []
        if self.intent == TaskIntent.INSPECT_ONLY and self.has_edit:
            problems.append("inspect_only_with_edit")
        if (
            self.phase == AgentPhase.DONE
            and self.outcome == TaskOutcome.EDITED_AND_VALIDATED
            and not self.acceptance_passed
        ):
            problems.append("finished_without_acceptance")
        if (
            self.active_evidence_edit_revision is not None
            and self.active_evidence_edit_revision != self.edit_revision
        ):
            problems.append("stale_validation_revision")
        if tool_batch_open and next_provider_call:
            problems.append("provider_call_during_open_tool_batch")
        return tuple(problems)

    # Kept as a narrow compatibility surface for callers constructing an
    # isolated state in tests. Production orchestration uses TaskRuntime.emit.
    def transition_for_tool(
        self,
        tool_name: str,
        *,
        success: bool,
        validation_outcome: ValidationOutcome | None = None,
        stale_edit: bool = False,
    ) -> AgentPhase:
        if self.phase in {AgentPhase.DONE, AgentPhase.BLOCKED}:
            return self.phase
        if stale_edit or validation_outcome == ValidationOutcome.FAILED:
            self.phase = AgentPhase.FIXING
        elif tool_name in {"patch_file", "replace_lines", "replace_symbol", "write_file"}:
            self.phase = AgentPhase.VALIDATING if success else AgentPhase.ACTING
        elif validation_outcome is not None:
            self.phase = AgentPhase.VALIDATING
        return self.phase

    def mark_finalizing(self) -> None:
        if self.phase not in {AgentPhase.DONE, AgentPhase.BLOCKED}:
            self.phase = AgentPhase.FINALIZING

    def require_action(self) -> None:
        if self.phase == AgentPhase.INSPECTING:
            self.phase = AgentPhase.ACTING

    def finish(self, outcome: TaskOutcome) -> None:
        self.outcome = outcome
        self.phase = AgentPhase.BLOCKED if outcome == TaskOutcome.BLOCKED else AgentPhase.DONE


def reduce_task_state(state: TaskState, event: RuntimeEvent) -> TaskState:
    """Pure state transition for every orchestration-significant event."""

    data = dict(event.data)
    sequence = state.event_sequence + 1
    if event.kind == RuntimeEventType.TASK_STARTED:
        return TaskState(
            run_id=str(data.get("run_id") or uuid4().hex),
            mode=data.get("mode"),
            intent=data.get("intent", TaskIntent.MODIFY),
            needs_plan=bool(data.get("needs_plan", False)),
            planning_activated=bool(data.get("planning_activated", False)),
            user_request=str(data.get("user_request", "")),
            final_response_mode=str(data.get("final_response_mode", "task_report")),
            target_paths=tuple(data.get("target_paths", ()) or ()),
            relevant_paths=tuple(data.get("target_paths", ()) or ()),
            edit_revision=max(0, int(data.get("edit_revision", 0))),
            validation_revision=max(0, int(data.get("validation_revision", 0))),
            has_edit=bool(data.get("has_edit", False)),
            acceptance_passed=bool(data.get("acceptance_passed", False)),
            relevant_validation_passed=bool(data.get("relevant_validation_passed", False)),
            full_validation_passed=bool(data.get("full_validation_passed", False)),
            latest_validation_outcome=data.get("latest_validation_outcome"),
            active_evidence_edit_revision=data.get("active_evidence_edit_revision"),
            requirement_ids=tuple(data.get("requirement_ids", ()) or ()),
            satisfied_requirement_ids=tuple(data.get("satisfied_requirement_ids", ()) or ()),
            remaining_steps=max(0, int(data.get("remaining_steps", 0))),
            event_sequence=sequence,
        )

    updates: dict[str, Any] = {"event_sequence": sequence}
    if event.kind == RuntimeEventType.BUDGET_UPDATED:
        updates.update(
            consumed_steps=max(0, int(data.get("consumed_steps", state.consumed_steps))),
            remaining_steps=max(0, int(data.get("remaining_steps", state.remaining_steps))),
        )
    elif event.kind == RuntimeEventType.CONTEXT_UPDATED:
        updates["relevant_paths"] = tuple(data.get("relevant_paths", ()) or ())
    elif event.kind == RuntimeEventType.MODE_ESCALATED:
        mode = data.get("mode", state.mode)
        order = {ExecutionMode.FAST: 0, ExecutionMode.STANDARD: 1, ExecutionMode.COMPLEX: 2}
        if state.mode is None or order.get(mode, -1) >= order.get(state.mode, -1):
            updates["mode"] = mode
    elif event.kind == RuntimeEventType.PLAN_ACTIVATED:
        updates.update(
            planning_activated=True,
            plan_revision=max(state.plan_revision + 1, int(data.get("plan_revision", 0))),
        )
    elif event.kind == RuntimeEventType.PLAN_RECONCILED:
        updates.update(
            planning_activated=bool(data.get("planning_activated", state.planning_activated)),
            plan_revision=max(state.plan_revision, int(data.get("plan_revision", state.plan_revision))),
            completed_plan_steps=tuple(data.get("completed_steps", state.completed_plan_steps) or ()),
            superseded_plan_steps=tuple(data.get("superseded_steps", state.superseded_plan_steps) or ()),
        )
    elif event.kind == RuntimeEventType.TOOL_STARTED:
        updates["active_tool"] = str(data.get("tool_name", "")) or None
    elif event.kind == RuntimeEventType.TOOL_FINISHED:
        updates["active_tool"] = None
        updates["consecutive_inspections"] = max(
            0, int(data.get("consecutive_inspections", state.consecutive_inspections))
        )
        updates["consecutive_no_state_change"] = max(
            0, int(data.get("consecutive_no_state_change", state.consecutive_no_state_change))
        )
    elif event.kind == RuntimeEventType.EDIT_APPLIED:
        revision = int(data.get("edit_revision", state.edit_revision + 1))
        updates.update(
            edit_revision=revision,
            has_edit=True,
            acceptance_passed=False,
            relevant_validation_passed=False,
            full_validation_passed=False,
            latest_validation_outcome=None,
            active_evidence_edit_revision=None,
            phase=AgentPhase.VALIDATING,
            consecutive_inspections=0,
            consecutive_no_state_change=0,
        )
    elif event.kind == RuntimeEventType.VALIDATION_OBSERVED:
        outcome = data.get("outcome")
        updates.update(
            validation_revision=max(
                state.validation_revision + 1,
                int(data.get("validation_revision", state.validation_revision + 1)),
            ),
            acceptance_passed=bool(data.get("acceptance_passed", state.acceptance_passed)),
            relevant_validation_passed=bool(
                data.get("relevant_validation_passed", state.relevant_validation_passed)
            ),
            full_validation_passed=bool(data.get("full_validation_passed", state.full_validation_passed)),
            latest_validation_outcome=outcome,
            active_evidence_edit_revision=data.get("evidence_edit_revision"),
            phase=AgentPhase.FIXING if outcome == ValidationOutcome.FAILED else AgentPhase.VALIDATING,
        )
    elif event.kind == RuntimeEventType.REQUIREMENTS_UPDATED:
        updates.update(
            requirement_ids=tuple(data.get("requirement_ids", state.requirement_ids) or ()),
            satisfied_requirement_ids=tuple(
                data.get("satisfied_requirement_ids", state.satisfied_requirement_ids) or ()
            ),
        )
    elif event.kind == RuntimeEventType.RECOVERY_STARTED:
        updates.update(
            recovery_level=max(state.recovery_level, int(data.get("level", state.recovery_level + 1))),
            phase=AgentPhase.FIXING,
        )
    elif event.kind == RuntimeEventType.ROLLBACK_APPLIED:
        revision = int(data.get("edit_revision", state.edit_revision + 1))
        updates.update(
            rollback_revision=max(state.rollback_revision + 1, int(data.get("rollback_revision", 0))),
            edit_revision=revision,
            acceptance_passed=False,
            relevant_validation_passed=False,
            full_validation_passed=False,
            active_evidence_edit_revision=None,
            latest_validation_outcome=None,
            phase=AgentPhase.VALIDATING,
        )
    elif event.kind == RuntimeEventType.PHASE_CHANGED:
        if state.phase not in {AgentPhase.DONE, AgentPhase.BLOCKED}:
            updates["phase"] = data.get("phase", state.phase)
    elif event.kind == RuntimeEventType.TASK_COMPLETED:
        updates.update(outcome=data.get("outcome", state.outcome), phase=AgentPhase.DONE)
    elif event.kind == RuntimeEventType.TASK_BLOCKED:
        updates.update(
            outcome=TaskOutcome.BLOCKED,
            phase=AgentPhase.BLOCKED,
            latest_blocker=str(data.get("reason", "")) or state.latest_blocker,
        )
    elif event.kind == RuntimeEventType.BUDGET_EXHAUSTED:
        updates["remaining_steps"] = 0
    return replace(state, **updates)


class TaskRuntime:
    """Own current state and an append-only bounded transition trace."""

    def __init__(self, state: TaskState | None = None, *, max_events: int = 2_000) -> None:
        self.state = state or TaskState()
        self.max_events = max(50, int(max_events))
        self.events: list[RuntimeEvent] = []

    def apply(self, event: RuntimeEvent) -> TaskState:
        next_state = reduce_task_state(self.state, event)
        violations = next_state.invariant_violations()
        if violations:
            raise ValueError("invalid task-state transition: " + ", ".join(violations))
        # Preserve object identity for read-only controller references while
        # still deriving every production transition through the pure reducer.
        self.state.__dict__.update(next_state.__dict__)
        self.events.append(event)
        if len(self.events) > self.max_events:
            del self.events[: len(self.events) - self.max_events]
        return self.state

    def emit(self, kind: RuntimeEventType, **data: Any) -> TaskState:
        return self.apply(RuntimeEvent.create(kind, **data))

    def can_continue(self) -> bool:
        return self.state.phase not in {AgentPhase.DONE, AgentPhase.BLOCKED} and self.state.remaining_steps > 0
