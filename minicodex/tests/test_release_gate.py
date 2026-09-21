import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ..evaluation.benchmark_v1 import BENCHMARK_VERSION
from ..evaluation.release_gate import ReleasePolicy, evaluate_summary, main as release_gate_main
from ..main import run_once
from ..workspace import WorkspaceConfig


def _passing_summary(*, task_count=30, runs=3):
    metrics = {
        "task_success_rate": 1.0,
        "first_pass_success_rate": 0.8,
        "failed_tool_call_rate": 0.01,
        "average_llm_calls": 5.0,
        "false_completion_rate": 0.0,
        "max_step_exhaustion_rate": 0.0,
        "wrong_validation_target_rate": 0.0,
        "unauthorized_edit_rate": 0.0,
        "wrong_file_edit_rate": 0.0,
        "ghost_step_rate": 0.0,
    }
    return {
        "metadata": {
            "benchmark_version": BENCHMARK_VERSION,
            "profile": "minicodex",
            "task_count": task_count,
            "runs": runs,
            "git_head": "abc123",
            "environment": {"ready": True},
        },
        "total_cases": task_count * runs,
        "metrics": metrics,
    }


def test_release_gate_accepts_full_repeated_safe_benchmark():
    report = evaluate_summary(_passing_summary(), expected_git_head="abc123")
    assert report.passed


def test_release_gate_rejects_smoke_or_safety_regression():
    summary = _passing_summary(task_count=8, runs=1)
    summary["metrics"]["false_completion_rate"] = 0.125
    report = evaluate_summary(summary)
    assert not report.passed
    assert {failure.check for failure in report.failures} >= {"task_count", "runs", "false_completion_rate"}


def test_release_gate_cli_can_check_saved_summary_without_local_subprocesses(tmp_path, capsys):
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(_passing_summary(runs=1)))
    release_gate_main(["--summary", str(path), "--minimum-runs", "1", "--skip-local",
                       "--allow-other-commit"])
    assert "PASSED" in capsys.readouterr().out


def test_run_once_executes_one_prompt_and_always_saves_trace(monkeypatch, tmp_path):
    saved = []
    agent = SimpleNamespace(run=lambda prompt: f"done: {prompt}")
    recorder = SimpleNamespace(save_jsonl=lambda path: saved.append(path))
    monkeypatch.setattr("minicodex.main.build_agent", lambda *args, **kwargs: (agent, recorder, object()))
    config = WorkspaceConfig.create(tmp_path)
    runtime = tmp_path / ".runtime"
    config = replace(config, runtime_root=runtime, sandbox_root=runtime / "sandbox",
                     trace_root=runtime / "traces")

    assert run_once(config, "  fix it  ") == "done: fix it"
    assert saved == [config.trace_root / "latest.jsonl"]


def test_run_once_rejects_empty_prompt(tmp_path):
    with pytest.raises(ValueError, match="不能为空"):
        run_once(WorkspaceConfig.create(tmp_path), "   ")
