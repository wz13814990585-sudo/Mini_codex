"""Fresh evidence required for explicit semantic plan completion."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StepEvidence:
    step_id: int
    edit_revision: int
    sequence: int
    source_tool: str
    path: str | None
    summary: str


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
        self._sequence += 1
        evidence = StepEvidence(
            step_id=int(step_id),
            edit_revision=int(edit_revision),
            sequence=self._sequence,
            source_tool=tool_name,
            path=str((arguments or {}).get("path", "")).strip() or None,
            summary=str(getattr(result, "summary", ""))[:500],
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
