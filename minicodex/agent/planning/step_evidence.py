"""Fresh evidence required for explicit semantic plan completion."""

from dataclasses import dataclass
from enum import Enum


class EvidenceStrength(str, Enum):
    OBSERVATION = "observation"
    IMPLEMENTATION = "implementation"
    VALIDATION = "validation"


@dataclass(frozen=True)
class StepEvidence:
    step_id: int
    edit_revision: int
    sequence: int
    source_tool: str
    path: str | None
    summary: str
    strength: EvidenceStrength


class StepEvidenceStore:
    EVIDENCE_TOOLS = {
        "read_file",
        "search_code",
        "search_symbol",
        "write_file",
        "patch_file",
        "replace_lines",
        "replace_symbol",
        "run_tests",
        "validate_static_web",
        "run_command",
    }
    IMPLEMENTATION_TOOLS = {
        "write_file", "patch_file", "replace_lines", "replace_symbol"
    }
    VALIDATION_TOOLS = {"run_tests", "validate_static_web", "run_command"}

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._sequence = 0
        self._items: list[StepEvidence] = []

    def record(self, *, step_id, edit_revision, tool_name, arguments, result):
        if (
            step_id is None
            or tool_name not in self.EVIDENCE_TOOLS
            or not getattr(result, "success", False)
        ):
            return None
        strength = self._strength(tool_name)
        if strength == EvidenceStrength.VALIDATION and not self._validation_passed(
            tool_name, arguments or {}, result
        ):
            return None
        self._sequence += 1
        evidence = StepEvidence(
            step_id=int(step_id),
            edit_revision=int(edit_revision),
            sequence=self._sequence,
            source_tool=tool_name,
            path=str((arguments or {}).get("path", "")).strip() or None,
            summary=str(getattr(result, "summary", ""))[:500],
            strength=strength,
        )
        self._items.append(evidence)
        return evidence

    def fresh_for(self, *, step_id: int, edit_revision: int) -> tuple[StepEvidence, ...]:
        return tuple(
            item
            for item in self._items
            if item.step_id == step_id and item.edit_revision == edit_revision
        )

    def has_fresh(self, *, step_id: int, edit_revision: int) -> bool:
        return bool(self.fresh_for(step_id=step_id, edit_revision=edit_revision))

    def has_sufficient(self, *, step_id: int, edit_revision: int) -> bool:
        items = self.fresh_for(step_id=step_id, edit_revision=edit_revision)
        strengths = {item.strength for item in items}
        return bool(
            EvidenceStrength.VALIDATION in strengths
            or {
                EvidenceStrength.IMPLEMENTATION,
                EvidenceStrength.OBSERVATION,
            }.issubset(strengths)
        )

    def has_validation(self, *, step_id: int, edit_revision: int) -> bool:
        return any(
            item.strength == EvidenceStrength.VALIDATION
            for item in self.fresh_for(step_id=step_id, edit_revision=edit_revision)
        )

    @classmethod
    def _strength(cls, tool_name: str) -> EvidenceStrength:
        if tool_name in cls.IMPLEMENTATION_TOOLS:
            return EvidenceStrength.IMPLEMENTATION
        if tool_name in cls.VALIDATION_TOOLS:
            return EvidenceStrength.VALIDATION
        return EvidenceStrength.OBSERVATION

    @staticmethod
    def _validation_passed(tool_name: str, arguments: dict, result) -> bool:
        data = getattr(result, "data", {}) or {}
        if tool_name == "validate_static_web":
            return str(data.get("outcome", "")).lower() == "passed"
        if tool_name == "run_tests":
            return data.get("tests_passed") is True
        if tool_name == "run_command":
            return (
                str(arguments.get("purpose", "diagnostic")).lower() == "acceptance"
                and data.get("command_succeeded") is True
            )
        return False
