from types import SimpleNamespace

from ..agent.orchestration.validation_orchestrator import (
    active_plan_incomplete,
    can_finish_edit_task,
)
from ..agent.validation import (
    ValidationPipeline,
)


# =============================================================
# Fake Plan
# =============================================================


class FakePlan:

    def __init__(
        self,
        completed: bool,
    ):

        self.completed = (
            completed
        )

    def is_completed(
        self,
    ) -> bool:

        return (
            self.completed
        )


# =============================================================
# Helpers
# =============================================================


def make_agent(
    *,
    plan=None,
):

    pipeline = (
        ValidationPipeline()
    )

    return SimpleNamespace(
        active_plan=(
            plan
        ),
        validation_pipeline=(
            pipeline
        ),
    )


def make_green_revision(
    agent,
):

    agent.validation_pipeline.record_edit()

    agent.validation_pipeline.state.acceptance_passed = (
        True
    )

    agent.validation_pipeline.state.full_passed = (
        True
    )


# =============================================================
# No Plan
# =============================================================


def test_no_plan_does_not_block_completion():

    agent = (
        make_agent(
            plan=None
        )
    )

    make_green_revision(
        agent
    )

    assert (
        active_plan_incomplete(
            agent
        )
        is False
    )

    assert (
        can_finish_edit_task(
            agent
        )
        is True
    )


# =============================================================
# Incomplete Plan
# =============================================================


def test_incomplete_plan_blocks_green_validation():

    agent = (
        make_agent(
            plan=(
                FakePlan(
                    completed=False
                )
            )
        )
    )

    make_green_revision(
        agent
    )

    assert (
        active_plan_incomplete(
            agent
        )
        is True
    )

    assert (
        can_finish_edit_task(
            agent
        )
        is False
    )


# =============================================================
# Completed Plan
# =============================================================


def test_completed_plan_allows_green_validation():

    agent = (
        make_agent(
            plan=(
                FakePlan(
                    completed=True
                )
            )
        )
    )

    make_green_revision(
        agent
    )

    assert (
        active_plan_incomplete(
            agent
        )
        is False
    )

    assert (
        can_finish_edit_task(
            agent
        )
        is True
    )


# =============================================================
# Plan Cannot Bypass Missing Acceptance
# =============================================================


def test_completed_plan_does_not_bypass_missing_acceptance():

    agent = (
        make_agent(
            plan=(
                FakePlan(
                    completed=True
                )
            )
        )
    )

    agent.validation_pipeline.record_edit()

    agent.validation_pipeline.state.full_passed = (
        True
    )

    agent.validation_pipeline.state.acceptance_passed = (
        False
    )

    assert (
        can_finish_edit_task(
            agent
        )
        is False
    )


# =============================================================
# Plan Cannot Bypass Missing Regression
# =============================================================


def test_completed_plan_does_not_bypass_missing_regression():

    agent = (
        make_agent(
            plan=(
                FakePlan(
                    completed=True
                )
            )
        )
    )

    agent.validation_pipeline.record_edit()

    agent.validation_pipeline.state.acceptance_passed = (
        True
    )

    agent.validation_pipeline.state.full_passed = (
        False
    )

    assert (
        can_finish_edit_task(
            agent
        )
        is False
    )


# =============================================================
# Incomplete Plan Blocks Even Fully Green Revision
# =============================================================


def test_incomplete_plan_blocks_fully_green_revision():

    agent = (
        make_agent(
            plan=(
                FakePlan(
                    completed=False
                )
            )
        )
    )

    agent.validation_pipeline.record_edit()

    agent.validation_pipeline.state.acceptance_passed = (
        True
    )

    agent.validation_pipeline.state.full_passed = (
        True
    )

    assert (
        can_finish_edit_task(
            agent
        )
        is False
    )
