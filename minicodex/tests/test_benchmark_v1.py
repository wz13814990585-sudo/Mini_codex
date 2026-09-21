from collections import Counter
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from ..agent.observability import ExecutionMetrics
from ..agent.routing import ExecutionMode, TaskIntent
from ..agent.validation import ValidationEvidence, ValidationOutcome, ValidationPurpose, ValidationScope
from ..evaluation.benchmark_v1 import BENCHMARK_VERSION, catalog_by_id, fixtures, smoke_fixtures
from ..evaluation.checks import EvaluationCheckRunner
from ..evaluation.harness import EvaluationHarness
from ..evaluation.models import EvaluationCase, EvaluationCheck, EvaluationResult, EvaluationSummary
from ..evaluation.models import FAILURE_CATEGORIES
from ..evaluation.profiles import EvaluationProfile, benchmark_policy
from ..evaluation.preflight import BenchmarkPreflightResult, PreflightCheck, benchmark_preflight
from ..evaluation.reporting import (
    compare_profiles,
    comparison_markdown,
    failure_clusters,
    failure_markdown,
    summary_markdown,
    write_jsonl,
)
from ..evaluation.run_benchmark import benchmark_workspace_is_isolated
from ..agent.runtime.git_awareness import GitRepositoryInspector
from ..llm.types import TokenUsage
from ..tools.filesystem import ReadFileTool


EXPECTED_CATEGORIES = {
    "create": 5,
    "modify": 7,
    "fix": 8,
    "refactor": 4,
    "dependency": 2,
    "follow_up": 2,
    "already_satisfied": 2,
}


def test_live_benchmark_workspace_is_outside_repository(tmp_path):
    workspace = tmp_path / "minicodex-bench-case"
    workspace.mkdir()
    assert benchmark_workspace_is_isolated(workspace)
    assert GitRepositoryInspector(workspace).snapshot().is_repo is False


def test_catalog_is_fixed_diverse_and_versioned():
    catalog = fixtures()
    assert len(catalog) == 30
    assert Counter(item.case.category for item in catalog) == EXPECTED_CATEGORIES
    assert len({item.case.case_id for item in catalog}) == 30
    assert all(item.case.benchmark_version == BENCHMARK_VERSION for item in catalog)
    tags = {tag for item in catalog for tag in item.case.tags}
    assert {"python", "fastapi", "flask", "html", "javascript", "typescript"} <= tags
    assert all(
        item.case.expected_edit_paths
        for item in catalog if item.case.category != "already_satisfied"
    )


def test_smoke_subset_is_stable_and_representative():
    assert [item.case.case_id for item in smoke_fixtures()] == [
        "create_calculator_service",
        "create_fastapi_login",
        "create_web_counter",
        "modify_web_keyboard",
        "modify_typescript_sum",
        "fix_python_double",
        "fix_python_sort_key",
        "already_health_ok",
    ]


def test_every_case_has_only_hidden_behavioral_oracle():
    for fixture in fixtures():
        assert fixture.case.checks
        assert all(check.kind in {"pytest_passes", "python_oracle"} for check in fixture.case.checks)
        assert all(path == "test_oracle.py" for path, _ in fixture.oracle_files)
        assert all(path != "test_oracle.py" for path, _ in fixture.workspace_files)


def test_catalog_oracles_reject_broken_seeds_and_accept_satisfied_seeds(tmp_path):
    runner = EvaluationCheckRunner()
    for fixture in fixtures():
        workspace = tmp_path / "workspaces" / fixture.case.case_id
        oracle = tmp_path / "oracles" / fixture.case.case_id
        for relative, content in fixture.workspace_files:
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        for relative, content in fixture.oracle_files:
            target = oracle / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        result = runner.run(
            check=fixture.case.checks[0], workspace=workspace, output="", oracle_root=oracle
        )
        assert result.passed is (fixture.case.category == "already_satisfied"), fixture.case.case_id


def test_workspace_tool_cannot_escape_to_hidden_oracle(tmp_path):
    workspace = tmp_path / "workspace"
    oracle = tmp_path / "oracle"
    workspace.mkdir()
    oracle.mkdir()
    (oracle / "test_oracle.py").write_text("SECRET=True\n")
    with pytest.raises(ValueError, match="工作区之外"):
        ReadFileTool(workspace).execute("../oracle/test_oracle.py")


def test_hidden_oracle_is_materialized_only_after_agent_finishes(tmp_path):
    workspace, oracle = tmp_path / "workspace", tmp_path / "oracle"
    workspace.mkdir()
    (workspace / "value.py").write_text("VALUE=1\n")

    class Agent:
        def __init__(self):
            self.workspace = workspace
            self._benchmark_oracle_root = oracle
            self._benchmark_materialize_oracle = self.materialize
            self._benchmark_cleanup_oracle = lambda: shutil.rmtree(oracle)
            self.validation_pipeline = SimpleNamespace(state=SimpleNamespace(
                edit_revision=0, has_edit=False, acceptance_passed=False,
                full_passed=False, evidence_history=[]))
            self.token_metrics = SimpleNamespace(total=TokenUsage(), call_count=0)
            self.execution_metrics = ExecutionMetrics(final_outcome="already_satisfied")
            self.execution_metrics.intent = "modify"
            self.active_plan = None

        def materialize(self):
            oracle.mkdir()
            (oracle / "test_oracle.py").write_text("def test_value():\n from value import VALUE\n assert VALUE == 1\n")

        def run(self, prompt):
            assert not oracle.exists()
            return "already satisfied"

    case = EvaluationCase("hidden", "check", checks=(EvaluationCheck("pytest_passes", path="test_oracle.py"),),
                          require_completion_ready=False)
    result = EvaluationHarness(agent_factory=lambda case: Agent()).run_case(case)
    assert result.oracle_passed is True
    assert not oracle.exists()


def _evidence(outcome, revision, *, purpose=ValidationPurpose.ACCEPTANCE,
              scope=ValidationScope.TARGETED, check_id=""):
    return ValidationEvidence(
        tool_name="run_tests", execution_succeeded=True, outcome=outcome,
        scope=scope, purpose=purpose,
        edit_revision=revision, check_id=check_id,
    )


class MetricAgent:
    def __init__(self, workspace, evidence, *, revision=1, repair_attempts=0,
                 outcome="edited_and_validated", max_steps=False,
                 intent=TaskIntent.MODIFY, edit_count=None, tool_count=4,
                 edited_paths=(), rollback_count=0, redundant_reads=0,
                 no_progress=0, validation_plan=None):
        edit_count = revision if edit_count is None else edit_count
        self.workspace = workspace
        self.validation_pipeline = SimpleNamespace(state=SimpleNamespace(
            edit_revision=revision, has_edit=bool(edit_count),
            acceptance_passed=any(item.purpose == ValidationPurpose.ACCEPTANCE and
                                  item.outcome == ValidationOutcome.PASSED for item in evidence),
            full_passed=False, evidence_history=list(evidence),
            plan=validation_plan,
        ))
        self.token_metrics = SimpleNamespace(
            total=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15), call_count=2)
        self.execution_metrics = ExecutionMetrics(
            intent=intent.value, edit_tool_count=edit_count, tool_call_count=tool_count,
            validation_tool_count=len(evidence), final_outcome=outcome,
            repair_attempts=repair_attempts, agent_steps=3,
            max_steps_exhausted=max_steps, edited_paths=list(edited_paths),
            rollback_count=rollback_count, redundant_reads=redundant_reads,
            no_progress_detections=no_progress,
        )
        self.execution_route = SimpleNamespace(intent=intent)
        # Work plan has steps only — must not be used for first-pass check binding.
        self.active_plan = SimpleNamespace(steps=("edit",), is_completed=lambda: True)
        self.concrete_blockers = []

    def run(self, prompt):
        return "done"


def _metric_case(tmp_path, agent, *, expected_edit_paths=(), allowed_edit_paths=()):
    (tmp_path / "answer.py").write_text("OK=True\n")
    case = EvaluationCase("metric", "fix", checks=(EvaluationCheck("file_contains", path="answer.py", expected="OK=True"),),
                          category="fix", benchmark_version=BENCHMARK_VERSION)
    case = EvaluationCase(
        **{**case.__dict__, "expected_edit_paths": tuple(expected_edit_paths),
           "allowed_edit_paths": tuple(allowed_edit_paths)}
    )
    return EvaluationHarness(agent_factory=lambda case: agent, profile="minicodex",
                             model="test", run_index=2).run_case(case)


def test_unbound_acceptance_is_not_first_pass_success_but_metrics_remain(tmp_path):
    result = _metric_case(tmp_path, MetricAgent(tmp_path, [_evidence(ValidationOutcome.PASSED, 1)]))
    assert result.first_pass_success is False
    assert result.agent_steps == 3
    assert result.validation_runs == result.validation_passes == 1
    assert result.validation_failures == result.validation_inconclusive == 0
    assert result.run_index == 2 and result.benchmark_version == BENCHMARK_VERSION


def test_bound_acceptance_on_validation_plan_is_first_pass_success(tmp_path):
    """first_pass must bind to validation_pipeline.state.plan checks, not active_plan steps."""
    plan = SimpleNamespace(checks=(
        SimpleNamespace(id="V1", required=True, purpose=ValidationPurpose.ACCEPTANCE),
    ))
    agent = MetricAgent(
        tmp_path,
        [
            _evidence(ValidationOutcome.FAILED, 0, check_id="V1"),
            _evidence(ValidationOutcome.PASSED, 1, check_id="V1"),
        ],
        validation_plan=plan,
    )
    result = _metric_case(tmp_path, agent)
    assert result.first_pass_success is True
    assert result.recovery_entered is False
    assert result.repair_attempts == 0


def test_active_plan_without_validation_checks_cannot_prove_first_pass(tmp_path):
    """Regression: work-plan active_plan has no .checks; must not silently zero first-pass."""
    agent = MetricAgent(
        tmp_path,
        [_evidence(ValidationOutcome.PASSED, 1, check_id="V1")],
        validation_plan=None,
    )
    # active_plan is still present (steps only) — first_pass must stay False.
    assert getattr(agent.active_plan, "steps", None)
    assert not hasattr(agent.active_plan, "checks")
    result = _metric_case(tmp_path, agent)
    assert result.first_pass_success is False


def test_recovery_semantics_require_corrective_action_and_oracle_success(tmp_path):
    result = _metric_case(tmp_path, MetricAgent(
        tmp_path,
        [_evidence(ValidationOutcome.FAILED, 1), _evidence(ValidationOutcome.PASSED, 2)],
        revision=2,
        repair_attempts=1,
    ))
    assert result.first_pass_success is False
    assert result.recovery_entered is True
    assert result.recovery_success is True
    assert (result.validation_passes, result.validation_failures) == (1, 1)


def test_first_pass_rejects_regression_only_later_edit_rollback_and_oracle_failure(tmp_path):
    regression = _metric_case(tmp_path, MetricAgent(tmp_path, [
        _evidence(ValidationOutcome.PASSED, 1, purpose=ValidationPurpose.REGRESSION)
    ]))
    assert regression.first_pass_success is False

    later_edit = _metric_case(tmp_path, MetricAgent(
        tmp_path, [_evidence(ValidationOutcome.PASSED, 1)], revision=2,
    ))
    assert later_edit.first_pass_success is False

    rolled_back = _metric_case(tmp_path, MetricAgent(
        tmp_path, [_evidence(ValidationOutcome.PASSED, 1)], rollback_count=1,
    ))
    assert rolled_back.first_pass_success is False

    missing = tmp_path / "missing"
    oracle_failure = EvaluationHarness(agent_factory=lambda case: MetricAgent(
        tmp_path, [_evidence(ValidationOutcome.PASSED, 1)]
    )).run_case(EvaluationCase(
        "oracle-fail", "fix", checks=(EvaluationCheck("file_exists", path=str(missing)),)
    ))
    assert oracle_failure.oracle_passed is False
    assert oracle_failure.first_pass_success is False


def test_unauthorized_and_wrong_file_edits_are_distinct(tmp_path):
    inspect_agent = MetricAgent(
        tmp_path, [], intent=TaskIntent.INSPECT_ONLY, edited_paths=("answer.py",),
        outcome="incomplete",
    )
    unauthorized = _metric_case(tmp_path, inspect_agent, expected_edit_paths=("answer.py",))
    assert unauthorized.unauthorized_edit is True
    assert unauthorized.wrong_file_edit is False
    assert unauthorized.failure_category == "unauthorized_edit"

    wrong_agent = MetricAgent(
        tmp_path, [], edited_paths=("README.md",), outcome="incomplete",
    )
    wrong = _metric_case(
        tmp_path, wrong_agent, expected_edit_paths=("src/parser.py",),
        allowed_edit_paths=("src/parser.py", "tests/test_parser.py"),
    )
    assert wrong.wrong_file_edit is True
    assert wrong.unauthorized_edit is False
    assert wrong.failure_category == "wrong_file_edit"


def test_legitimate_multifile_edit_is_not_wrong_file_edit(tmp_path):
    agent = MetricAgent(
        tmp_path, [_evidence(ValidationOutcome.PASSED, 2)], revision=2,
        edited_paths=("src/parser.py", "tests/test_parser.py"),
    )
    result = _metric_case(
        tmp_path, agent, expected_edit_paths=("src/parser.py",),
        allowed_edit_paths=("src/parser.py", "tests/test_parser.py"),
    )
    assert result.wrong_file_edit is False


def test_incomplete_alone_is_not_wrong_validation_target(tmp_path):
    agent = MetricAgent(
        tmp_path, [_evidence(ValidationOutcome.INCONCLUSIVE, 1)], outcome="incomplete",
    )
    result = _metric_case(tmp_path, agent)
    assert result.wrong_validation_target is False
    assert result.failure_category == "unknown"


def test_no_tools_and_repeated_reconnaissance_have_precise_categories(tmp_path):
    no_tools = MetricAgent(
        tmp_path, [], revision=0, edit_count=0, tool_count=0, outcome="incomplete",
    )
    assert _metric_case(tmp_path, no_tools).failure_category == "no_tool_loop"

    repeated = MetricAgent(
        tmp_path, [], revision=0, edit_count=0, tool_count=3,
        redundant_reads=1, outcome="incomplete",
    )
    assert _metric_case(tmp_path, repeated).failure_category == "repeated_reconnaissance"

    stalled = MetricAgent(
        tmp_path, [], revision=0, edit_count=0, tool_count=2,
        no_progress=1, outcome="incomplete",
    )
    assert _metric_case(tmp_path, stalled).failure_category == "no_progress"


def test_false_completion_uses_oracle_not_agent_claim(tmp_path):
    agent = MetricAgent(tmp_path, [_evidence(ValidationOutcome.PASSED, 1)])
    case = EvaluationCase("false", "fix", checks=(EvaluationCheck("file_exists", path="missing.py"),))
    result = EvaluationHarness(agent_factory=lambda case: agent).run_case(case)
    assert result.passed is False
    assert result.false_completion is True
    assert result.failure_category == "false_completion"


def test_max_steps_and_failure_category_are_recorded(tmp_path):
    agent = MetricAgent(tmp_path, [_evidence(ValidationOutcome.FAILED, 1)], outcome="incomplete", max_steps=True)
    agent.execution_metrics.wrong_validation_target_count = 1
    case = EvaluationCase("max", "fix", checks=(EvaluationCheck("file_exists", path="missing.py"),))
    result = EvaluationHarness(agent_factory=lambda case: agent).run_case(case)
    assert result.max_steps_exhausted is True
    assert result.failure_category == "max_steps_exhausted"
    assert result.terminal_failure_category == "max_steps_exhausted"
    assert result.failure_reason


def test_inconclusive_validation_and_wrong_target_are_recorded(tmp_path):
    agent = MetricAgent(tmp_path, [_evidence(ValidationOutcome.INCONCLUSIVE, 1)], outcome="incomplete")
    agent.execution_metrics.wrong_validation_target_count = 1
    agent.validation_pipeline.state.acceptance_passed = False
    agent.validation_pipeline.state.full_passed = False
    result = _metric_case(tmp_path, agent)
    assert result.validation_inconclusive == 1
    assert result.wrong_validation_target is True
    assert result.failure_category == "wrong_validation_target"


def test_failure_taxonomy_contract_is_complete():
    assert {
        "routing_failure", "requirement_failure", "planning_failure",
        "target_location_failure", "wrong_file_edit", "unauthorized_edit",
        "repeated_reconnaissance", "no_progress", "no_tool_loop", "tool_error",
        "edit_failure", "spec_binding_failure", "wrong_validation_target",
        "validation_failure", "regression_failure", "capability_missing",
        "environment_failure", "recovery_failure", "false_completion",
        "max_steps_exhausted", "oracle_failure", "unknown",
    } == set(FAILURE_CATEGORIES)


def test_summary_denominators_and_efficiency_metrics():
    summary = EvaluationSummary("run", results=[
        EvaluationResult("a", True, "", first_pass_success=True, recovery_entered=False,
                         validation_passes=2, validation_failures=0, tool_call_count=4,
                         failed_tool_call_count=1, agent_steps=2, llm_call_count=3,
                         total_tokens=100),
        EvaluationResult("b", True, "", recovery_entered=True, recovery_success=True,
                         validation_passes=1, validation_failures=1, tool_call_count=6,
                         agent_steps=4, llm_call_count=5, total_tokens=300),
        EvaluationResult("c", False, "", recovery_entered=True, recovery_success=False,
                         validation_inconclusive=1, false_completion=True, tool_call_count=2,
                         agent_steps=3, llm_call_count=2, total_tokens=200),
    ])
    metrics = summary.vibe_metrics()
    assert metrics["task_success_rate"] == 2 / 3
    assert metrics["first_pass_success_rate"] == 1 / 3
    assert metrics["recovery_success_rate"] == 1 / 2
    assert metrics["validation_pass_rate"] == 3 / 4
    assert metrics["false_completion_rate"] == 1 / 3
    assert metrics["tool_calls_per_success"] == 6
    assert metrics["median_tokens_per_success"] == 200
    assert metrics["average_failed_tool_calls"] == 1 / 3
    assert metrics["failed_tool_call_rate"] == 1 / 12
    assert metrics["ghost_step_count"] == 0
    assert metrics["ghost_step_rate"] == 0.0
    assert metrics["executed_tool_turn_count"] == 0
    assert metrics["blocked_tool_selection_count"] == 0
    assert metrics["productive_step_count"] == 0
    assert metrics["text_only_step_count"] == 0


def test_baseline_and_minicodex_share_budget_but_not_advanced_controls():
    baseline = benchmark_policy(EvaluationProfile.BASELINE, mode=ExecutionMode.STANDARD, max_steps=17)
    current = benchmark_policy(EvaluationProfile.MINICODEX, mode=ExecutionMode.STANDARD, max_steps=17)
    assert baseline.max_steps == current.max_steps == 17
    assert baseline.use_plan is baseline.enable_heavy_recovery is baseline.enable_replan is False
    assert current.use_plan is current.enable_heavy_recovery is current.enable_replan is True


def test_comparison_delta_and_case_groups():
    baseline = EvaluationSummary("baseline", [EvaluationResult(
        "a", False, "", tool_call_count=4, failed_tool_call_count=2,
    )])
    current = EvaluationSummary("minicodex", [EvaluationResult(
        "a", True, "", tool_call_count=2, failed_tool_call_count=0,
    )])
    report = compare_profiles(baseline, current)
    assert report["metrics"]["task_success_rate"]["delta"] == 1.0
    assert report["metrics"]["average_tool_calls"]["delta"] == -2
    assert report["metrics"]["average_failed_tool_calls"] == {
        "baseline": 2.0, "minicodex": 0.0, "delta": -2.0,
    }
    assert report["improved_cases"] == ["a"]
    markdown = comparison_markdown(report)
    assert "# Baseline 与 MiniCodex 对比" in markdown
    assert "| 指标 | Baseline | MiniCodex | 变化 |" in markdown
    assert "| 任务成功率 |" in markdown
    assert "| 首次修改成功率 |" in markdown
    assert "## 改善用例" in markdown
    assert "| task_success_rate |" not in markdown


def test_summary_and_failure_markdown_use_chinese_labels():
    summary = EvaluationSummary("demo-run", [
        EvaluationResult("a", True, ""),
        EvaluationResult("b", False, "", failure_category="no_progress", failure_reason="stalled"),
    ])
    summary_md = summary_markdown(summary)
    assert "用例数：2" in summary_md
    assert "| 指标 | 值 |" in summary_md
    assert "任务成功率" in summary_md
    assert "## 失败聚类" in summary_md
    assert "- no_progress: 1" in summary_md

    failure_md = failure_markdown(summary.results)
    assert "# 失败报告" in failure_md
    assert "共 2 次任务/运行；1 次通过；1 次失败。" in failure_md
    assert "## no_progress (1)" in failure_md

    clean = failure_markdown([EvaluationResult("ok", True, "")])
    assert "无失败。" in clean


def test_failure_clusters_are_deterministic():
    report = failure_clusters([
        EvaluationResult("a", False, "", failure_category="no_progress", failure_reason="none"),
        EvaluationResult("b", False, "", failure_category="no_progress", failure_reason="none"),
        EvaluationResult("c", True, ""),
    ])
    assert report["counts"] == {"no_progress": 2}
    assert report["failed"] == 2


def test_raw_results_never_overwrite_prior_run(tmp_path):
    path = tmp_path / "run_001.jsonl"
    write_jsonl(path, [EvaluationResult("a", True, "", run_index=1)])
    with pytest.raises(FileExistsError):
        write_jsonl(path, [EvaluationResult("a", True, "", run_index=1)])
    assert EvaluationResult("a", True, "").to_dict()["success"] is True


def test_raw_result_schema_contains_benchmark_contract():
    assert {
        "case_id", "run_index", "category", "tags", "profile", "model", "success",
        "first_pass_success", "final_outcome", "failure_category", "failure_reason",
        "false_completion", "max_steps_exhausted", "agent_steps", "tool_call_count",
        "llm_call_count", "inspection_tool_count", "edit_tool_count", "validation_tool_count",
        "validation_runs", "validation_passes", "validation_failures", "validation_inconclusive",
        "recovery_entered", "recovery_success", "repair_attempts", "rollback_count",
        "unauthorized_edit", "wrong_file_edit", "wrong_validation_target",
        "failed_tool_call_count", "failed_tool_call_rate", "repeated_action_count", "redundant_reads",
        "redundant_searches", "calls_before_first_edit", "calls_before_first_validation",
        "inspections_before_first_edit", "searches_before_first_edit", "time_to_first_edit",
        "prompt_tokens", "completion_tokens", "total_tokens", "routing_llm_calls",
        "requirements_llm_calls", "semantic_judge_llm_calls", "total_control_llm_calls",
        "cost_usd", "duration_seconds", "oracle_checks", "oracle_passed", "edit_revision",
        "benchmark_version",
    } <= EvaluationResult("case", False, "").to_dict().keys()


def test_live_cli_requires_explicit_configuration(monkeypatch):
    from ..evaluation.run_benchmark import main
    monkeypatch.delenv("MISSING_BENCHMARK_KEY", raising=False)
    with pytest.raises(SystemExit):
        main(["--profile", "minicodex", "--provider", "test", "--model", "model",
              "--api-key-env", "MISSING_BENCHMARK_KEY"])


def test_selected_case_preflight_only_requires_selected_dependencies():
    python_only = benchmark_preflight(
        (catalog_by_id()["fix_python_double"],),
        executable_finder=lambda name: None,
        module_finder=lambda name: object(),
    )
    assert python_only.ready is True
    assert python_only.required_executables == ()

    missing_node = benchmark_preflight(
        (catalog_by_id()["create_web_counter"],),
        executable_finder=lambda name: None,
        module_finder=lambda name: object(),
    )
    assert missing_node.ready is False
    assert missing_node.required_executables == ("node",)

    missing_fastapi = benchmark_preflight(
        (catalog_by_id()["create_fastapi_login"],),
        executable_finder=lambda name: f"/bin/{name}",
        module_finder=lambda name: None if name == "fastapi" else object(),
    )
    assert missing_fastapi.ready is False
    assert "fastapi" in missing_fastapi.required_python_modules


def test_full_catalog_derives_complete_environment_contract():
    result = benchmark_preflight(
        fixtures(), executable_finder=lambda name: f"/bin/{name}",
        module_finder=lambda name: object(),
    )
    assert result.required_executables == ("node", "npm")
    assert set(result.required_python_modules) == {
        "fastapi", "flask", "httpx", "packaging", "pytest",
    }
    assert result.ready is True


def test_preflight_failure_aborts_before_run_and_emits_no_results(monkeypatch, tmp_path):
    from ..evaluation import run_benchmark

    failed = BenchmarkPreflightResult(
        checks=(PreflightCheck("node", False, "未在 PATH 中找到", "executable"),),
        required_executables=("node",), required_python_modules=("pytest",),
    )
    monkeypatch.setattr(run_benchmark, "benchmark_preflight", lambda selected: failed)
    monkeypatch.setattr(
        run_benchmark, "_run_profile",
        lambda *args, **kwargs: pytest.fail("agent/model execution must not start"),
    )
    output = tmp_path / "benchmark-results"
    with pytest.raises(SystemExit) as exc:
        run_benchmark.main([
            "--profile", "minicodex", "--provider", "test", "--model", "model",
            "--case-id", "create_web_counter", "--output", str(output),
        ])
    assert exc.value.code == 2
    assert not output.exists()


def test_reproducibility_metadata_records_git_and_configuration(monkeypatch):
    from ..evaluation import run_benchmark
    monkeypatch.setattr(run_benchmark, "_git_head", lambda: "abc123")
    args = SimpleNamespace(provider="provider", model="model", temperature=0.2,
                           max_steps=12, runs=3)
    environment = {"ready": True, "checks": [{"name": "pytest", "available": True}]}
    metadata = run_benchmark._metadata(
        args, profile="baseline", task_count=30, timestamp="2026-01-01T00:00:00Z",
        environment=environment,
    )
    assert metadata["git_head"] == "abc123"
    assert metadata["benchmark_version"] == BENCHMARK_VERSION
    assert metadata["model_parameters"] == {"temperature": 0.2}
    assert metadata["task_count"] == 30 and metadata["runs"] == 3
    assert metadata["environment"] == environment
