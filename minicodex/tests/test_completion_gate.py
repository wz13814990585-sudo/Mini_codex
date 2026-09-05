from ..agent.completion import (
    CompletionGate,
    CompletionStatus,
)


def test_no_edit_cannot_complete():

    gate = (
        CompletionGate()
    )

    decision = (
        gate.evaluate(
            edit_revision=0,
            has_edit=False,
            acceptance_passed=False,
            full_validation_passed=True,
        )
    )

    assert (
        decision.status
        == CompletionStatus.NOT_READY
    )

    assert (
        decision.can_complete
        is False
    )


def test_full_tests_alone_are_not_enough():

    gate = (
        CompletionGate()
    )

    decision = (
        gate.evaluate(
            edit_revision=1,
            has_edit=True,
            acceptance_passed=False,
            full_validation_passed=True,
        )
    )

    assert (
        decision.status
        == (
            CompletionStatus
            .NEEDS_ACCEPTANCE
        )
    )

    assert (
        decision.can_complete
        is False
    )


def test_acceptance_alone_is_not_enough():

    gate = (
        CompletionGate()
    )

    decision = (
        gate.evaluate(
            edit_revision=1,
            has_edit=True,
            acceptance_passed=True,
            full_validation_passed=False,
        )
    )

    assert (
        decision.status
        == (
            CompletionStatus
            .NEEDS_FULL_VALIDATION
        )
    )

    assert (
        decision.can_complete
        is False
    )


def test_acceptance_and_full_validation_allow_completion():

    gate = (
        CompletionGate()
    )

    decision = (
        gate.evaluate(
            edit_revision=3,
            has_edit=True,
            acceptance_passed=True,
            full_validation_passed=True,
        )
    )

    assert (
        decision.status
        == CompletionStatus.READY
    )

    assert (
        decision.can_complete
        is True
    )

    assert (
        decision.edit_revision
        == 3
    )


def test_new_revision_requires_new_evidence():

    gate = (
        CompletionGate()
    )

    revision_one = (
        gate.evaluate(
            edit_revision=1,
            has_edit=True,
            acceptance_passed=True,
            full_validation_passed=True,
        )
    )

    assert (
        revision_one.can_complete
        is True
    )

    # New edit revision has invalidated validation state.
    revision_two = (
        gate.evaluate(
            edit_revision=2,
            has_edit=True,
            acceptance_passed=False,
            full_validation_passed=False,
        )
    )

    assert (
        revision_two.can_complete
        is False
    )