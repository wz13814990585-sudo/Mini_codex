"""Small deterministic proof obligations derived from typed contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum

from .contracts import (
    BrowserInteractionContract,
    FileContainsContract,
    FileExistsContract,
    HttpContract,
    SemanticContract,
    VerificationContract,
    contract_key,
)
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
    contract: VerificationContract
    required: bool = True
    strength: EvidenceStrength = EvidenceStrength.TARGETED
    revision: int = 0
    reason: str = "独立证明请求结果。"

    @property
    def contract_type(self) -> str:
        return self.contract.contract_type


@dataclass(frozen=True)
class ValidationPlan:
    checks: tuple[ValidationCheck, ...] = ()

    def at_revision(self, revision: int) -> "ValidationPlan":
        return replace(self, checks=tuple(replace(check, revision=revision) for check in self.checks))

    def for_requirement(self, requirement_id: str) -> tuple[ValidationCheck, ...]:
        return tuple(
            check for check in self.checks
            if check.required and requirement_id in check.requirement_ids
        )


class ValidationPlanner:
    """Materialize each typed contract once; identical contracts share proof."""

    def build(
        self,
        requirements,
        *,
        revision: int = 0,
        profile=None,
        paths=(),
        request="",
        mode=None,
        impact=None,
        available_capabilities=None,
    ) -> ValidationPlan:
        del profile, paths, request, mode, impact, available_capabilities
        grouped: dict[tuple, list] = {}
        for requirement in requirements.items:
            grouped.setdefault(contract_key(requirement.contract), []).append(requirement)

        checks: list[ValidationCheck] = []
        for items in grouped.values():
            contract = items[0].contract
            checks.append(ValidationCheck(
                id=f"V{len(checks) + 1}",
                requirement_ids=tuple(item.id for item in items),
                purpose=(
                    ValidationPurpose.REGRESSION
                    if any(item.category.value == "regression" for item in items)
                    else ValidationPurpose.ACCEPTANCE
                ),
                contract=contract,
                strength=self._strength(contract),
                revision=revision,
                reason="；".join(item.description for item in items),
            ))
        return ValidationPlan(tuple(checks))

    @staticmethod
    def _strength(contract: VerificationContract) -> EvidenceStrength:
        if isinstance(contract, (FileExistsContract, FileContainsContract)):
            return EvidenceStrength.STRUCTURE
        if isinstance(contract, SemanticContract):
            return EvidenceStrength.TARGETED
        if isinstance(contract, (HttpContract, BrowserInteractionContract)):
            return EvidenceStrength.RUNTIME
        return EvidenceStrength.TARGETED
