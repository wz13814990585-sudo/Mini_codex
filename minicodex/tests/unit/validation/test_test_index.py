from ....agent.validation import TestIndex
from ....agent.validation import TestTargetResolver
from ....agent.validation import ValidationSelector


def test_index_maps_ast_import_and_caches_by_revision(tmp_path):
    source = tmp_path / "pkg" / "worker.py"
    test = tmp_path / "tests" / "test_behavior.py"
    source.parent.mkdir()
    test.parent.mkdir()
    source.write_text("def work(): return 1\n", encoding="utf-8")
    test.write_text("from pkg.worker import work\n\ndef test_work(): assert work() == 1\n", encoding="utf-8")

    index = TestIndex(tmp_path)
    assert index.tests_for("pkg/worker.py", revision=1) == ("tests/test_behavior.py",)
    assert index.tests_for("pkg/worker.py", revision=1) == ("tests/test_behavior.py",)
    assert index.build_count == 1
    assert index.tests_for("pkg/worker.py", revision=2) == ("tests/test_behavior.py",)
    assert index.build_count == 2


def test_resolver_marks_import_link_as_regression_not_acceptance(tmp_path):
    source = tmp_path / "pkg" / "worker.py"
    test = tmp_path / "tests" / "test_behavior.py"
    source.parent.mkdir()
    test.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    test.write_text("import pkg.worker\n", encoding="utf-8")

    result = TestTargetResolver(tmp_path).resolve(("pkg/worker.py",), revision=3)

    assert result.selected_path == "tests/test_behavior.py"
    assert result.purpose == "regression"
    assert result.acceptance_supported is False


def test_selector_uses_import_link_only_as_regression(tmp_path):
    source = tmp_path / "pkg" / "worker.py"
    test = tmp_path / "tests" / "test_behavior.py"
    source.parent.mkdir()
    test.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    test.write_text("import pkg.worker\n", encoding="utf-8")
    selector = ValidationSelector(tmp_path)

    regression = selector.select(
        target_paths=("pkg/worker.py",),
        registered_tools={"run_tests", "run_command"},
        desired_purpose="regression",
    )
    acceptance = selector.select(
        target_paths=("pkg/worker.py",),
        registered_tools={"run_tests", "run_command"},
        desired_purpose="acceptance",
    )

    assert (regression.tool_name, regression.purpose) == ("run_tests", "regression")
    assert (acceptance.tool_name, acceptance.purpose) == ("run_command", "acceptance")
