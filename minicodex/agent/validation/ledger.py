"""Canonical validation history. Green projections are derived, never assigned."""
from dataclasses import dataclass, field, replace

from .evidence import ValidationEvidence, ValidationOutcome, ValidationPurpose, ValidationScope
from .plan import ValidationPlan


@dataclass
class ValidationLedger:
    edit_revision: int = 0
    has_edit: bool = False
    evidence_sequence: int = 0
    evidence_history: list[ValidationEvidence] = field(default_factory=list)
    baseline_by_key: dict[str, ValidationEvidence] = field(default_factory=dict)
    plan: ValidationPlan = field(default_factory=ValidationPlan)

    def reset(self):
        self.edit_revision = 0
        self.has_edit = False
        self.evidence_sequence = 0
        self.evidence_history.clear()
        self.baseline_by_key.clear()
        self.plan = ValidationPlan()

    def record_edit(self, *, owned=True):
        self.edit_revision += 1
        self.has_edit = self.has_edit or owned
        self.plan = self.plan.at_revision(self.edit_revision)
        return self.edit_revision

    @property
    def latest_evidence(self):
        return next((e for e in reversed(self.evidence_history)
                     if e.edit_revision == self.edit_revision), None)

    def record(self, evidence):
        check = next((c for c in self.plan.checks if c.id == evidence.check_id), None)
        eligible = (evidence.execution_succeeded and evidence.outcome != ValidationOutcome.INCONCLUSIVE
                    and not evidence.agent_test_only and check is not None and evidence.strength >= check.strength)
        if check and not check.target and eligible:
            already_bound = any(c.id != check.id and c.target == evidence.target and c.purpose == check.purpose
                                for c in self.plan.checks)
            if already_bound or not evidence.target:
                evidence = replace(evidence, check_id="", requirement_ids=())
            else:
                self.plan = replace(self.plan, checks=tuple(
                    replace(c, target=evidence.target) if c.id == check.id else c for c in self.plan.checks))
        comparable = [e for e in self.evidence_history
                      if e.edit_revision == evidence.edit_revision
                      and e.validation_key == evidence.validation_key]
        # A contradiction needs two subsequent identical outcomes to stabilize.
        unstable = bool(comparable and comparable[-1].outcome != evidence.outcome)
        if comparable and comparable[-1].unstable:
            unstable = len(comparable) < 2 or any(
                e.outcome != evidence.outcome for e in comparable[-2:])
        evidence = replace(evidence, unstable=unstable)
        self.evidence_history.append(evidence)
        self.evidence_sequence += 1
        if evidence.edit_revision == 0 and evidence.purpose == ValidationPurpose.REGRESSION:
            self.baseline_by_key.setdefault(evidence.validation_key, evidence)
        return evidence

    def proof(self, check_id):
        check = next((c for c in self.plan.checks if c.id == check_id), None)
        if check is None or check.revision != self.edit_revision:
            return None
        current = [e for e in self.evidence_history
                   if e.edit_revision == self.edit_revision and e.check_id == check_id]
        if not current:
            return None
        latest = current[-1]
        # Even unbound contradictory observations invalidate the same executed check.
        same_target = [e for e in self.evidence_history
                       if e.edit_revision == self.edit_revision
                       and e.validation_key == latest.validation_key]
        if same_target[-1].outcome != ValidationOutcome.PASSED or same_target[-1].unstable:
            return None
        if (latest.outcome != ValidationOutcome.PASSED or latest.unstable
                or not latest.execution_succeeded or latest.strength < check.strength
                or latest.purpose != check.purpose or latest.agent_test_only
                or not set(check.requirement_ids).issubset(latest.requirement_ids)):
            return None
        if not check.target or check.target != latest.target:
            return None
        if check.capability not in {"validation.structure", "validation.behavior"} and latest.capability != check.capability:
            return None
        return latest

    def _passed(self, purpose, scope=None):
        latest = {}
        for e in self.evidence_history:
            if e.edit_revision == self.edit_revision and e.purpose == purpose:
                latest[e.validation_key] = e
        selected = [e for e in latest.values() if scope is None or e.scope == scope]
        if scope == ValidationScope.TARGETED:
            selected = [e for e in selected if e.strength >= 2 and not (e.capability == "process.run" and e.strength != 2)]
        return bool(selected) and all(e.outcome == ValidationOutcome.PASSED and not e.unstable and not e.agent_test_only
                                      for e in selected)

    @property
    def acceptance_passed(self):
        checks = [c for c in self.plan.checks if c.required and c.purpose == ValidationPurpose.ACCEPTANCE]
        if checks:
            return all(self.proof(c.id) is not None for c in checks)
        return self._passed(ValidationPurpose.ACCEPTANCE)

    @property
    def targeted_passed(self):
        return self._passed(ValidationPurpose.REGRESSION, ValidationScope.TARGETED)

    @property
    def full_passed(self):
        return self._passed(ValidationPurpose.REGRESSION, ValidationScope.FULL) and self._passed(ValidationPurpose.REGRESSION)
