"""Real normalized evidence for tests; never assign green-state flags."""
from minicodex.agent.validation.evidence import ValidationEvidence, ValidationOutcome, ValidationPurpose, ValidationScope
from minicodex.agent.validation.contracts import CommandContract
from minicodex.agent.validation.plan import EvidenceStrength, ValidationCheck, ValidationPlan


def record_evidence(ledger, category, passed=True):
    purpose = ValidationPurpose.ACCEPTANCE if category == "acceptance_passed" else ValidationPurpose.REGRESSION
    scope = ValidationScope.FULL if category == "full_passed" else ValidationScope.TARGETED
    check_id = f"fixture_{category}"
    strength = EvidenceStrength.FULL if scope == ValidationScope.FULL else (
        EvidenceStrength.REGRESSION if purpose == ValidationPurpose.REGRESSION
        else EvidenceStrength.TARGETED
    )
    if not any(check.id == check_id for check in ledger.plan.checks):
        ledger.plan = ValidationPlan((*ledger.plan.checks, ValidationCheck(
            check_id, ("R_fixture",) if purpose == ValidationPurpose.ACCEPTANCE else (),
            purpose, CommandContract(category), strength=strength,
            revision=ledger.edit_revision,
        )))
    return ledger.record(ValidationEvidence(
        tool_name="fixture_validator", execution_succeeded=True,
        outcome=ValidationOutcome.PASSED if passed else ValidationOutcome.FAILED,
        purpose=purpose, scope=scope, edit_revision=ledger.edit_revision, path=category,
        check_id=check_id,
        requirement_ids=("R_fixture",) if purpose == ValidationPurpose.ACCEPTANCE else (),
        strength=int(strength),
    ))
