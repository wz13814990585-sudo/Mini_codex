"""Requirement-bound verification contracts, independent of tool names."""
from dataclasses import dataclass, replace
from enum import IntEnum
import re

from .evidence import ValidationPurpose


class EvidenceStrength(IntEnum):
    STRUCTURE = 0
    LINT = 1
    TARGETED = 2
    REGRESSION = 3
    BUILD = 4
    RUNTIME = 5
    FULL = 6


@dataclass(frozen=True)
class ValidationCheck:
    id: str
    requirement_ids: tuple[str, ...]
    purpose: ValidationPurpose
    target: str = ""
    capability: str = "validation.behavior"
    required: bool = True
    strength: EvidenceStrength = EvidenceStrength.TARGETED
    revision: int = 0
    milestone: str = "task"
    reason: str = "Prove the requested outcome independently."


@dataclass(frozen=True)
class ValidationPlan:
    checks: tuple[ValidationCheck, ...] = ()

    def at_revision(self, revision: int):
        return replace(self, checks=tuple(replace(c, revision=revision) for c in self.checks))

    def for_requirement(self, requirement_id: str):
        return tuple(c for c in self.checks if requirement_id in c.requirement_ids and c.required)


class ValidationPlanner:
    def build(self, requirements, *, revision=0, profile=None, paths=(), request=""):
        checks = []
        for item in requirements.items:
            structural = item.kind.value == "structural"
            browser_runtime = (any(p.endswith(".html") for p in item.paths)
                               and re.search(r"game|playable|keypress|keyboard|click|游戏|交互", item.description, re.I))
            checks.append(ValidationCheck(
                id=f"V{len(checks) + 1}", requirement_ids=(item.id,),
                purpose=(ValidationPurpose.REGRESSION if item.category.value == "regression"
                         else ValidationPurpose.ACCEPTANCE),
                target=item.validation_target,
                capability="validation.browser" if browser_runtime else "validation.structure" if structural else "validation.behavior",
                strength=EvidenceStrength.RUNTIME if browser_runtime else EvidenceStrength.STRUCTURE if structural else EvidenceStrength.TARGETED,
                revision=revision, reason=item.description,
            ))
        if profile is not None and checks:
            from .ladder import VerificationLadder
            for rung in VerificationLadder().select(profile, paths, request):
                if rung.command and rung.strength in {EvidenceStrength.LINT, EvidenceStrength.BUILD}:
                    checks.append(ValidationCheck(f"V{len(checks) + 1}", (), ValidationPurpose.REGRESSION,
                        target=rung.command, capability="process.run", strength=rung.strength,
                        revision=revision, reason=rung.reason))
        return ValidationPlan(tuple(checks))


class RequirementEvidenceResolver:
    """No edits, global green flags, or another requirement's checks count."""

    def resolve(self, requirements, ledger):
        for item in requirements.items:
            checks = ledger.plan.for_requirement(item.id)
            proofs = [ledger.proof(c.id) for c in checks]
            item.satisfied = bool(checks) and all(proofs)
            item.evidence_revision = ledger.edit_revision if item.satisfied else None
            item.evidence = [p.validation_key for p in proofs if p is not None]
