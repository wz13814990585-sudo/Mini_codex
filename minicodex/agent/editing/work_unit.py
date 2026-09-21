"""A bounded semantic edit group with explicit validation milestones."""

from dataclasses import dataclass, replace
from enum import Enum


class WorkUnitStatus(str, Enum):
    OPEN = "open"
    READY_FOR_VALIDATION = "ready_for_validation"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class WorkUnit:
    id: str
    requirement_ids: tuple[str, ...]
    intended_paths: tuple[str, ...]
    start_revision: int
    milestone_check_ids: tuple[str, ...] = ()
    edited_paths: tuple[str, ...] = ()
    edits: int = 0
    edit_budget: int = 8
    status: WorkUnitStatus = WorkUnitStatus.OPEN

    @property
    def max_edits(self):
        return self.edit_budget

    @property
    def closed(self):
        return self.status in {WorkUnitStatus.COMPLETED, WorkUnitStatus.FAILED}

    @property
    def milestone_due(self):
        return self.status == WorkUnitStatus.READY_FOR_VALIDATION or self.edits >= self.edit_budget

    @property
    def permits_intermediate_syntax(self):
        return not self.closed and len(self.intended_paths) > 1 and not self.milestone_due

    def record_edit(self, path):
        edits = self.edits + 1
        return replace(self, edits=edits,
                       edited_paths=tuple(dict.fromkeys((*self.edited_paths, path))),
                       status=WorkUnitStatus.READY_FOR_VALIDATION if edits >= self.edit_budget else WorkUnitStatus.OPEN)

    def begin_validation(self):
        return replace(self, status=WorkUnitStatus.VALIDATING)

    def resolve_milestone(self, *, passed: bool, all_resolved: bool):
        if all_resolved:
            return replace(self, status=WorkUnitStatus.COMPLETED)
        return replace(self, status=WorkUnitStatus.FAILED if not passed else WorkUnitStatus.READY_FOR_VALIDATION)
