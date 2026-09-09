import pytest

from ..tools.execution.run_tests import (
    RunTestsTool,
    extract_failure_paths,
)


def test_acceptance_validation_rejects_full_suite(
    tmp_path,
):

    tool = (
        RunTestsTool(
            workspace=(
                tmp_path
            )
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "specific test path"
        ),
    ):

        tool.execute(
            path=".",
            purpose=(
                "acceptance"
            ),
        )


def test_invalid_validation_purpose_is_rejected(
    tmp_path,
):

    tool = (
        RunTestsTool(
            workspace=(
                tmp_path
            )
        )
    )

    with pytest.raises(
        ValueError,
        match="purpose",
    ):

        tool.execute(
            path="tests",
            purpose=(
                "something_else"
            ),
        )


# =============================================================
# Workspace Escape
# =============================================================


def test_run_tests_rejects_outside_workspace(
    tmp_path,
):

    tool = (
        RunTestsTool(
            workspace=(
                tmp_path
            )
        )
    )

    with pytest.raises(
        ValueError,
        match="workspace",
    ):

        tool.execute(
            path=(
                "../outside"
            ),
            purpose=(
                "regression"
            ),
        )


# =============================================================
# Actual Sandboxed pytest
# =============================================================


def test_run_tests_executes_inside_sandbox(
    tmp_path,
):

    tests_dir = (
        tmp_path
        / "tests"
    )

    tests_dir.mkdir()

    test_file = (
        tests_dir
        / "test_example.py"
    )

    test_file.write_text(
        (
            "def test_example():\n"
            "    assert 1 + 1 == 2\n"
        ),
        encoding="utf-8",
    )

    tool = (
        RunTestsTool(
            workspace=(
                tmp_path
            )
        )
    )

    result = (
        tool.execute(
            path=(
                "tests/test_example.py"
            ),
            purpose=(
                "acceptance"
            ),
        )
    )

    assert (
        result.success
        is True
    )

    assert (
        result.data[
            "tests_passed"
        ]
        is True
    )

    assert (
        result.data[
            "passed"
        ]
        == 1
    )

    assert (
        result.data[
            "sandbox"
        ][
            "mode"
        ]
        == "process"
    )

    assert (
        result.data[
            "sandbox"
        ][
            "environment_sanitized"
        ]
        is True
    )


# =============================================================
# Failing Tests Are Validation Failure,
# Not Tool-Execution Failure
# =============================================================


def test_failing_pytest_still_returns_tool_result(
    tmp_path,
):

    tests_dir = (
        tmp_path
        / "tests"
    )

    tests_dir.mkdir()

    test_file = (
        tests_dir
        / "test_failure.py"
    )

    test_file.write_text(
        (
            "def test_failure():\n"
            "    assert False\n"
        ),
        encoding="utf-8",
    )

    tool = (
        RunTestsTool(
            workspace=(
                tmp_path
            )
        )
    )

    result = (
        tool.execute(
            path=(
                "tests/test_failure.py"
            ),
            purpose=(
                "acceptance"
            ),
        )
    )

    # pytest itself executed successfully as a tool.
    assert (
        result.success
        is True
    )

    # But behavioral validation failed.
    assert (
        result.data[
            "tests_passed"
        ]
        is False
    )

    assert (
        result.data[
            "failed"
        ]
        == 1
    )

    assert result.data["failure_paths"] == ["tests/test_failure.py"]


def test_failure_paths_include_repo_local_traceback_sources(tmp_path):
    test_path = tmp_path / "tests/test_example.py"
    source_path = tmp_path / "pkg/example.py"
    test_path.parent.mkdir(parents=True)
    source_path.parent.mkdir(parents=True)
    test_path.write_text("", encoding="utf-8")
    source_path.write_text("", encoding="utf-8")

    paths = extract_failure_paths(
        stdout=(
            "pkg/example.py:12: ValueError\n"
            "FAILED tests/test_example.py::test_example - ValueError\n"
        ),
        stderr="/outside/not_relevant.py:3: ignored",
        workspace=tmp_path,
    )

    assert paths == ["tests/test_example.py", "pkg/example.py"]


def test_acceptance_rejects_source_module_as_test_target(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/example.py").write_text("value = 1\n", encoding="utf-8")
    tool = RunTestsTool(workspace=tmp_path)

    with pytest.raises(ValueError, match="source module"):
        tool.execute(path="pkg/example.py", purpose="acceptance")
