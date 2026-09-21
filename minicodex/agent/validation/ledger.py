"""Canonical current-revision proof ledger."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .evidence import (
    ExecutionStatus,
    ValidationEvidence,
    ValidationOutcome,
    ValidationPurpose,
    ValidationScope,
)
from .plan import ValidationPlan


@dataclass
class ValidationLedger:
    edit_revision: int = 0
    has_edit: bool = False
    evidence_sequence: int = 0
    evidence_history: list[ValidationEvidence] = field(default_factory=list)
    execution_observations: list[dict] = field(default_factory=list)
    blocked_checks: dict[str, str] = field(default_factory=dict)
    baseline_by_key: dict[str, ValidationEvidence] = field(default_factory=dict)
    plan: ValidationPlan = field(default_factory=ValidationPlan)

    def reset(self) -> None:
        self.edit_revision = 0
        self.has_edit = False
        self.evidence_sequence = 0
        self.evidence_history.clear()
        self.execution_observations.clear()
        self.blocked_checks.clear()
        self.baseline_by_key.clear()
        self.plan = ValidationPlan()

    def record_edit(self, *, owned: bool = True) -> int:
        self.edit_revision += 1
        self.has_edit = self.has_edit or owned
        self.plan = self.plan.at_revision(self.edit_revision)
        self.blocked_checks.clear()
        return self.edit_revision

    @property
    def latest_evidence(self) -> ValidationEvidence | None:
        return next((
            evidence for evidence in reversed(self.evidence_history)
            if evidence.edit_revision == self.edit_revision
        ), None)

    @property
    def required_checks(self):
        return tuple(check for check in self.plan.checks if check.required)

    def observe_execution(self, **observation) -> None:
        self.execution_observations.append({
            "edit_revision": self.edit_revision,
            **observation,
        })

    def mark_blocked(self, check_id: str, reason: str) -> None:
        self.blocked_checks[check_id] = reason

    def record(self, evidence: ValidationEvidence) -> ValidationEvidence | None:
        """Record only actual validator executions with explicit check identity."""

        if evidence.execution_status != ExecutionStatus.EXECUTED:
            self.observe_execution(
                check_id=evidence.check_id,
                execution_status=evidence.execution_status.value,
                reason=evidence.summary,
            )
            return None
        check = next((item for item in self.plan.checks if item.id == evidence.check_id), None)
        if check is None or evidence.edit_revision != self.edit_revision:
            self.observe_execution(
                check_id=evidence.check_id,
                execution_status=ExecutionStatus.EXECUTED.value,
                outcome=evidence.outcome.value,
                proof_accepted=False,
                reason="unbound_or_stale",
            )
            evidence = replace(evidence, check_id="", requirement_ids=())
        else:
            evidence = replace(evidence, requirement_ids=check.requirement_ids)

        comparable = [
            item for item in self.evidence_history
            if item.edit_revision == evidence.edit_revision
            and item.check_id == evidence.check_id
            and item.validation_key == evidence.validation_key
            and item.execution_status == ExecutionStatus.EXECUTED
            and item.outcome in {ValidationOutcome.PASSED, ValidationOutcome.FAILED}
        ]
        decisive = evidence.outcome in {ValidationOutcome.PASSED, ValidationOutcome.FAILED}
        unstable = bool(
            evidence.check_id and decisive and comparable
            and any(item.outcome != evidence.outcome for item in comparable)
        )
        if comparable and any(item.unstable for item in comparable):
            unstable = True
        evidence = replace(evidence, unstable=unstable)
        self.evidence_history.append(evidence)
        self.evidence_sequence += 1
        if evidence.edit_revision == 0 and evidence.purpose == ValidationPurpose.REGRESSION:
            self.baseline_by_key.setdefault(evidence.validation_key, evidence)
        return evidence

    def proof(self, check_id: str) -> ValidationEvidence | None:
        check = next((item for item in self.plan.checks if item.id == check_id), None)
        if check is None or check.revision != self.edit_revision:
            return None
        current = [
            item for item in self.evidence_history
            if item.edit_revision == self.edit_revision and item.check_id == check_id
            and item.execution_status == ExecutionStatus.EXECUTED
        ]
        decisive = [
            item for item in current
            if item.outcome in {ValidationOutcome.PASSED, ValidationOutcome.FAILED}
        ]
        if not decisive or any(item.unstable for item in decisive):
            return None
        outcomes = {item.outcome for item in decisive}
        if outcomes != {ValidationOutcome.PASSED}:
            return None
        latest = decisive[-1]
        if (
            latest.strength < check.strength
            or latest.purpose != check.purpose
            or latest.agent_test_only
            or not set(check.requirement_ids).issubset(latest.requirement_ids)
        ):
            return None
        return latest

    @property
    def acceptance_passed(self) -> bool:
        checks = [
            check for check in self.required_checks
            if check.purpose == ValidationPurpose.ACCEPTANCE
        ]
        return bool(checks) and all(self.proof(check.id) is not None for check in checks)

    @property
    def targeted_passed(self) -> bool:
        checks = [
            check for check in self.required_checks
            if check.purpose == ValidationPurpose.REGRESSION
            and check.strength.value < 6
        ]
        return bool(checks) and all(self.proof(check.id) is not None for check in checks)

    @property
    def full_passed(self) -> bool:
        checks = [
            check for check in self.required_checks
            if check.purpose == ValidationPurpose.REGRESSION
            and check.strength.value >= 6
        ]
        return bool(checks) and all(self.proof(check.id) is not None for check in checks)
