from ..agent.plan_quality import PlanNormalizer
from ..agent.state import PlanStep


def test_broad_semantic_step_is_marked_but_not_naively_split():
    step = PlanStep(
        id=3,
        description=(
            "Add automatic falling, movement, acceleration, rotation, "
            "locking, line clearing, scoring, game over and restart"
        ),
    )

    normalized = PlanNormalizer().normalize([step])

    assert normalized == [step]
    assert step.requires_semantic_completion is True
    assert step.quality_warnings


def test_machine_checkable_step_is_not_marked_semantic():
    step = PlanStep(
        id=1,
        description="Create and validate the HTML shell",
        acceptance_criteria=[
            {"type": "file_exists", "path": "index.html"}
        ],
    )

    PlanNormalizer().normalize([step])

    assert step.requires_semantic_completion is False
    assert step.quality_warnings == []
