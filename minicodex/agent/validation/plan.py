"""Requirement-bound verification contracts, independent of tool names."""
from dataclasses import dataclass, replace
from enum import IntEnum

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
    observable: str = ""


@dataclass(frozen=True)
class ValidationPlan:
    checks: tuple[ValidationCheck, ...] = ()

    def at_revision(self, revision: int):
        return replace(self, checks=tuple(replace(c, revision=revision) for c in self.checks))

    def for_requirement(self, requirement_id: str):
        return tuple(c for c in self.checks if requirement_id in c.requirement_ids and c.required)


class ValidationPlanner:
    def build(self, requirements, *, revision=0, profile=None, paths=(), request="", mode=None,
              impact=None, available_capabilities=None):
        checks = []
        from .ladder import VerificationLadder
        rungs = VerificationLadder().select(profile, paths, request, mode=mode, impact=impact) if profile is not None else ()
        available = frozenset(available_capabilities or ())
        # A browser/service check is itself the acceptance proof when this
        # workspace has no focused test target.  Do not manufacture a second,
        # generic behaviour check that the same runtime observation cannot prove.
        runtime_rung = next((rung for rung in rungs
                             if rung.strength == EvidenceStrength.RUNTIME
                             and (not available or rung.capability in available)), None)
        commands = dict(getattr(profile, "commands", ()) or ())
        has_focused_test = bool(commands.get("test") or getattr(impact, "tests", ()))
        for item in requirements.items:
            structural = item.kind.value == "structural"
            semantic = item.kind.value == "semantic"
            runtime_acceptance = runtime_rung if not (structural or semantic or has_focused_test) else None
            checks.append(ValidationCheck(
                id=f"V{len(checks) + 1}", requirement_ids=(item.id,),
                purpose=(ValidationPurpose.REGRESSION if item.category.value == "regression"
                         else ValidationPurpose.ACCEPTANCE),
                capability=("validation.structure" if structural or semantic
                            else runtime_acceptance.capability if runtime_acceptance else "validation.behavior"),
                strength=(EvidenceStrength.STRUCTURE if structural or semantic
                          else runtime_acceptance.strength if runtime_acceptance else EvidenceStrength.TARGETED),
                revision=revision, milestone="work_unit" if len(paths) > 1 else "task",
                reason=runtime_acceptance.reason if runtime_acceptance else item.description,
                observable=item.observable,
            ))
        for rung in rungs:
            if available and rung.capability not in available:
                continue
            if rung.strength in {EvidenceStrength.STRUCTURE, EvidenceStrength.TARGETED} and rung.purpose == ValidationPurpose.ACCEPTANCE:
                continue
            if rung.strength == EvidenceStrength.RUNTIME and not has_focused_test:
                continue
            if rung.strength == EvidenceStrength.REGRESSION and not (rung.command or getattr(impact, "tests", ())):
                continue
            requirement_ids = (tuple(item.id for item in requirements.items
                                    if item.kind.value == "behavioral")
                               if rung.strength == EvidenceStrength.RUNTIME else ())
            if rung.strength == EvidenceStrength.RUNTIME and not requirement_ids:
                continue
            checks.append(ValidationCheck(
                f"V{len(checks) + 1}", requirement_ids, rung.purpose,
                target=rung.command if rung.capability == "process.run" else "",
                capability=rung.capability, strength=rung.strength, revision=revision,
                milestone="task", reason=rung.reason,
            ))
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
