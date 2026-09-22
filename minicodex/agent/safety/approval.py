"""Thread-safe human approval coordination for host applications."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import Condition, RLock
import time
import uuid
from typing import Any, Callable

from ..observability.redaction import redact
from ..runtime.execution_control import ACTIVE_CANCELLATION
from .safety import InterventionCategory, SafetyDecision


class ApprovalChoice(str, Enum):
    """Decisions a human may make for one caution-level operation."""

    ALLOW_ONCE = "allow_once"
    ALLOW_TASK = "allow_task"
    REJECT = "reject"


@dataclass(frozen=True)
class ApprovalRequest:
    """Bounded, redacted description of an operation awaiting a human."""

    request_id: str
    tool_name: str
    rule: str
    reason: str
    level: str
    path: str | None
    command: str | None
    arguments: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ApprovalCoordinator:
    """Pause one Agent worker until its local host records a decision.

    Only operations the deterministic safety policy already classifies as
    allowed ``CAUTION`` decisions can enter this coordinator. Hard denials are
    never made overridable by a UI decision.
    """

    _VISIBLE_ARGUMENTS = frozenset({
        "argv", "command", "import_name", "package", "path", "port", "url",
    })

    def __init__(self, *, timeout_seconds: float = 300.0) -> None:
        self.timeout_seconds = max(0.01, float(timeout_seconds))
        self._condition = Condition(RLock())
        self._pending: ApprovalRequest | None = None
        self._choice: ApprovalChoice | None = None
        self._allowed_rules: set[str] = set()
        self._closed_reason: str | None = None
        self._resolution_source: str | None = None
        self._audit: list[dict[str, Any]] = []
        self._audit_sequence = 0
        self._event_sink: Callable[[str, dict[str, Any]], Any] | None = None

    def begin_task(self) -> None:
        """Reset task-scoped grants before a new task starts."""

        with self._condition:
            if self._pending is not None:
                raise RuntimeError("Cannot begin a task while approval is pending.")
            self._choice = None
            self._allowed_rules.clear()
            self._closed_reason = None
            self._resolution_source = None
            self._audit.clear()
            self._audit_sequence = 0
            self._event_sink = None

    def set_event_sink(
        self,
        sink: Callable[[str, dict[str, Any]], Any] | None,
    ) -> None:
        """Attach the current task Trace sink after its recorder is created."""

        with self._condition:
            self._event_sink = sink

    def intervene(self, category, decision: SafetyDecision, prepared) -> bool:
        """SafetyToolExecutor hook; block until approval or rejection."""

        if (
            category != InterventionCategory.APPROVAL
            or not decision.allowed
            or not decision.requires_attention
        ):
            return False

        with self._condition:
            if decision.rule in self._allowed_rules:
                return True
            if self._pending is not None:
                # Tool execution is sequential today. Fail closed if a future
                # executor violates that invariant instead of replacing a
                # request another thread is reviewing.
                return False

            self._pending = self._build_request(decision, prepared)
            self._choice = None
            self._closed_reason = None
            self._resolution_source = None
            self._record_event("approval_requested", self._pending.to_dict())
            self._condition.notify_all()
            deadline = time.monotonic() + self.timeout_seconds

            while self._choice is None:
                token = ACTIVE_CANCELLATION.get()
                if token is not None and token.is_cancelled:
                    self._closed_reason = token.reason or "Task cancelled."
                    self._resolution_source = "cancelled"
                    self._choice = ApprovalChoice.REJECT
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._closed_reason = "Approval request timed out."
                    self._resolution_source = "timeout"
                    self._choice = ApprovalChoice.REJECT
                    break
                self._condition.wait(min(0.1, remaining))

            choice = self._choice
            resolution = {
                **self._pending.to_dict(),
                "decision": choice.value,
                "resolution": self._resolution_source or "user",
            }
            if self._closed_reason:
                resolution["reason"] = self._closed_reason
            self._record_event("approval_resolved", resolution)
            if choice == ApprovalChoice.ALLOW_TASK:
                self._allowed_rules.add(decision.rule)
            self._pending = None
            self._choice = None
            self._condition.notify_all()
            return choice in {ApprovalChoice.ALLOW_ONCE, ApprovalChoice.ALLOW_TASK}

    def resolve(self, request_id: str, choice: str | ApprovalChoice) -> dict[str, Any]:
        """Resolve exactly the request currently visible to the user."""

        try:
            normalized = ApprovalChoice(choice)
        except ValueError as exc:
            raise ValueError("Unknown approval decision.") from exc
        with self._condition:
            if self._pending is None:
                raise ValueError("No operation is awaiting approval.")
            if str(request_id or "") != self._pending.request_id:
                raise ValueError("Approval request is stale.")
            payload = self._pending.to_dict()
            payload["decision"] = normalized.value
            self._resolution_source = "user"
            self._choice = normalized
            self._condition.notify_all()
            return payload

    def cancel_pending(self, reason: str = "Task cancelled.") -> bool:
        """Reject a pending operation so cooperative task cancellation can finish."""

        with self._condition:
            if self._pending is None or self._choice is not None:
                return False
            self._closed_reason = str(reason or "Task cancelled.")
            self._resolution_source = "cancelled"
            self._choice = ApprovalChoice.REJECT
            self._condition.notify_all()
            return True

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                "pending": self._pending.to_dict() if self._pending is not None else None,
                "allowed_rules": sorted(self._allowed_rules),
                "audit": [dict(event) for event in self._audit],
            }

    def _record_event(self, event_type: str, data: dict[str, Any]) -> None:
        self._audit_sequence += 1
        event = {
            "sequence": self._audit_sequence,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": redact(data),
        }
        self._audit.append(event)
        if len(self._audit) > 100:
            self._audit = self._audit[-100:]
        if self._event_sink is not None:
            try:
                self._event_sink(event_type, event["data"])
            except Exception:
                # Audit observation must never change the permission decision.
                pass

    @classmethod
    def _build_request(cls, decision: SafetyDecision, prepared) -> ApprovalRequest:
        arguments = {
            str(key): cls._bounded(value)
            for key, value in dict(getattr(prepared, "arguments", {}) or {}).items()
            if str(key) in cls._VISIBLE_ARGUMENTS
        }
        return ApprovalRequest(
            request_id=uuid.uuid4().hex,
            tool_name=str(getattr(prepared, "tool_name", decision.tool_name)),
            rule=decision.rule,
            reason=decision.reason,
            level=decision.level.value,
            path=decision.path,
            command=cls._bounded(decision.command) if decision.command is not None else None,
            arguments=redact(arguments),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _bounded(value: Any) -> Any:
        cleaned = redact(value)
        if isinstance(cleaned, str):
            return cleaned if len(cleaned) <= 1000 else f"{cleaned[:997]}..."
        if isinstance(cleaned, list):
            return [ApprovalCoordinator._bounded(item) for item in cleaned[:20]]
        if isinstance(cleaned, tuple):
            return [ApprovalCoordinator._bounded(item) for item in cleaned[:20]]
        return cleaned
