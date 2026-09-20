from ....agent.validation import TestIndex, TestTargetContract
from ....agent.validation import TestTargetResolver
from ....agent.validation import ValidatorResolver
from ....agent.validation.plan import EvidenceStrength, ValidationCheck
from ....agent.validation.evidence import ValidationPurpose
from ....tools.registry import ToolRegistry


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


def test_resolver_uses_import_link_only_as_regression(tmp_path):
    source = tmp_path / "pkg" / "worker.py"
    test = tmp_path / "tests" / "test_behavior.py"
    source.parent.mkdir()
    test.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    test.write_text("import pkg.worker\n", encoding="utf-8")
    class TestTool:
        name = "remote_test_backend"
        capabilities = frozenset({"test.run"})
    registry = ToolRegistry()
    registry.register(TestTool())
    check = ValidationCheck("V1", (), ValidationPurpose.REGRESSION,
                            TestTargetContract("tests/test_behavior.py"),
                            strength=EvidenceStrength.REGRESSION)
    resolved = ValidatorResolver(tmp_path).resolve(check, registry=registry, paths=("pkg/worker.py",))
    assert resolved.tool_name == "remote_test_backend"
    assert resolved.arguments["path"] == "tests/test_behavior.py"
