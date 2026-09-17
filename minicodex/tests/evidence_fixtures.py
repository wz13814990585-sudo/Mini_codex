"""Real normalized evidence for tests; never assign green-state flags."""
from minicodex.agent.validation.evidence import ValidationEvidence, ValidationOutcome, ValidationPurpose, ValidationScope


def record_evidence(ledger, category, passed=True):
    purpose = ValidationPurpose.ACCEPTANCE if category == "acceptance_passed" else ValidationPurpose.REGRESSION
    scope = ValidationScope.FULL if category == "full_passed" else ValidationScope.TARGETED
    return ledger.record(ValidationEvidence(
        tool_name="fixture_validator", execution_succeeded=True,
        outcome=ValidationOutcome.PASSED if passed else ValidationOutcome.FAILED,
        purpose=purpose, scope=scope, edit_revision=ledger.edit_revision, path=category,
    ))
