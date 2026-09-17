"""A bounded cohesive edit group, distinct from a task plan step."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class WorkUnit:
    id: str
    target_paths: tuple[str, ...]
    start_revision: int
    edited_paths: tuple[str, ...] = ()
    edits: int = 0
    max_edits: int = 8
    closed: bool = False

    @property
    def milestone_due(self):
        return self.edits >= self.max_edits

    @property
    def permits_intermediate_syntax(self):
        return not self.closed and len(self.target_paths) > 1 and not self.milestone_due

    def record_edit(self, path):
        return replace(self, edits=self.edits + 1,
                       edited_paths=tuple(dict.fromkeys((*self.edited_paths, path))))
