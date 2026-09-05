import pytest

from ..tools.run_tests import RunTestsTool


def test_acceptance_validation_rejects_full_suite(
    tmp_path,
):

    tool = RunTestsTool(
        workspace=tmp_path
    )

    with pytest.raises(
        ValueError,
        match=(
            "specific test path"
        ),
    ):

        tool.execute(
            path=".",
            purpose="acceptance",
        )


def test_invalid_validation_purpose_is_rejected(
    tmp_path,
):

    tool = RunTestsTool(
        workspace=tmp_path
    )

    with pytest.raises(
        ValueError,
        match="purpose",
    ):

        tool.execute(
            path="tests",
            purpose="something_else",
        )