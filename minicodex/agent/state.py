from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PlanStep:
    id: int
    description: str
    status: StepStatus = StepStatus.PENDING
    acceptance_criteria: list[
        dict[str, Any]
    ] = field(default_factory=list)
    requires_semantic_completion: bool = False
    quality_warnings: list[str] = field(default_factory=list)

    # 当前 Plan Step 遇到的工具调用失败次数
    attempts: int = 0

    def increment_attempt(self) -> None:
        self.attempts += 1

    def reset_attempts(self) -> None:
        self.attempts = 0

    @classmethod
    def from_payload(
        cls,
        *,
        step_id: int,
        payload,
    ) -> "PlanStep":
        if isinstance(payload, str):
            return cls(
                id=step_id,
                description=payload,
            )

        if not isinstance(payload, dict):
            raise ValueError(
                "Plan step must be a string or object."
            )

        description = str(
            payload.get("description", "")
        ).strip()
        if not description:
            raise ValueError(
                "Plan step description is required."
            )

        raw_criteria = payload.get(
            "acceptance_criteria",
            [],
        )
        criteria = (
            [
                dict(item)
                for item in raw_criteria
                if isinstance(item, dict)
            ]
            if isinstance(raw_criteria, list)
            else []
        )

        return cls(
            id=step_id,
            description=description,
            acceptance_criteria=criteria,
        )


@dataclass
class AgentPlan:
    goal: str
    steps: list[PlanStep] = field(
        default_factory=list
    )
    completed_history: list[PlanStep] = field(
        default_factory=list
    )

    def all_steps(self) -> list[PlanStep]:
        return [*self.completed_history, *self.steps]

    def get_current_step(self) -> PlanStep | None:
        for step in self.steps:
            if step.status in {
                StepStatus.PENDING,
                StepStatus.IN_PROGRESS,
            }:
                return step

        return None

    def start_current_step(self) -> PlanStep | None:
        step = self.get_current_step()

        if step is not None:
            step.status = StepStatus.IN_PROGRESS

        return step

    def complete_current_step(self) -> PlanStep | None:
        step = self.get_current_step()

        if step is None:
            return None

        step.status = StepStatus.COMPLETED
        self.steps.remove(step)
        self.completed_history.append(step)
        return step

    def fail_current_step(self) -> PlanStep | None:
        step = self.get_current_step()

        if step is not None:
            step.status = StepStatus.FAILED

        return step

    def is_completed(self) -> bool:
        if self.get_current_step() is not None:
            return False

        if any(
            step.status == StepStatus.FAILED
            for step in self.steps
        ):
            return False

        if self.completed_history:
            return True

        return bool(self.steps) and all(
            step.status == StepStatus.COMPLETED
            for step in self.steps
        )
