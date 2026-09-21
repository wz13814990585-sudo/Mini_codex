"""Deterministic local and Benchmark V1 release gate for MiniCodex."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
import sys

from .benchmark_v1 import BENCHMARK_VERSION
from ..main import APPLICATION_ROOT


@dataclass(frozen=True)
class ReleasePolicy:
    minimum_task_count: int = 30
    minimum_runs: int = 3
    minimum_success_rate: float = 1.0
    minimum_first_pass_success_rate: float = 0.70
    maximum_failed_tool_call_rate: float = 0.05
    maximum_average_llm_calls: float = 8.0


@dataclass(frozen=True)
class GateFailure:
    check: str
    expected: str
    actual: object


@dataclass
class GateReport:
    failures: list[GateFailure] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def evaluate_summary(document: dict, *, policy: ReleasePolicy | None = None,
                     expected_git_head: str | None = None) -> GateReport:
    """Evaluate a saved online benchmark without making provider calls."""
    policy = policy or ReleasePolicy()
    metadata = document.get("metadata") or {}
    metrics = document.get("metrics") or document.get("vibebench") or {}
    report = GateReport()

    def equal(check: str, actual, expected) -> None:
        if actual != expected:
            report.failures.append(GateFailure(check, repr(expected), actual))

    def at_least(check: str, actual, expected: float | int) -> None:
        if not isinstance(actual, (int, float)) or actual < expected:
            report.failures.append(GateFailure(check, f">= {expected}", actual))

    def at_most(check: str, actual, expected: float | int) -> None:
        if not isinstance(actual, (int, float)) or actual > expected:
            report.failures.append(GateFailure(check, f"<= {expected}", actual))

    equal("benchmark_version", metadata.get("benchmark_version"), BENCHMARK_VERSION)
    equal("profile", metadata.get("profile"), "minicodex")
    equal("environment_ready", (metadata.get("environment") or {}).get("ready"), True)
    at_least("task_count", metadata.get("task_count"), policy.minimum_task_count)
    at_least("runs", metadata.get("runs"), policy.minimum_runs)
    expected_total = metadata.get("task_count", 0) * metadata.get("runs", 0)
    equal("total_cases", document.get("total_cases"), expected_total)
    at_least("task_success_rate", metrics.get("task_success_rate"), policy.minimum_success_rate)
    at_least("first_pass_success_rate", metrics.get("first_pass_success_rate"),
             policy.minimum_first_pass_success_rate)
    at_most("failed_tool_call_rate", metrics.get("failed_tool_call_rate"),
            policy.maximum_failed_tool_call_rate)
    at_most("average_llm_calls", metrics.get("average_llm_calls"),
            policy.maximum_average_llm_calls)
    for metric in (
        "false_completion_rate",
        "max_step_exhaustion_rate",
        "wrong_validation_target_rate",
        "unauthorized_edit_rate",
        "wrong_file_edit_rate",
        "ghost_step_rate",
    ):
        equal(metric, metrics.get(metric), 0.0)
    if expected_git_head is not None:
        equal("git_head", metadata.get("git_head"), expected_git_head)
    return report


def _git_head() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=APPLICATION_ROOT, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _run_local_checks() -> list[GateFailure]:
    commands = (
        ("compileall", [sys.executable, "-m", "compileall", "-q", "minicodex"]),
        ("pytest", [sys.executable, "-m", "pytest", "-q", "--tb=short"]),
        ("harness_bench", [sys.executable, "-m", "minicodex.evaluation.vibebench"]),
    )
    failures = []
    for name, command in commands:
        result = subprocess.run(command, cwd=APPLICATION_ROOT, text=True, capture_output=True)
        if result.returncode:
            detail = (result.stdout + result.stderr).strip()[-2000:]
            failures.append(GateFailure(name, "exit code 0", detail or result.returncode))
            continue
        if name == "harness_bench":
            try:
                summary = json.loads(result.stdout)
                passed = summary["passed_cases"]
                total = summary["total_cases"]
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                failures.append(GateFailure(name, "valid JSON summary", str(exc)))
            else:
                if passed != total:
                    failures.append(GateFailure(name, f"{total}/{total} passed", f"{passed}/{total}"))
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行 MiniCodex 产品发布门禁")
    parser.add_argument("--summary", type=Path,
                        help="完整在线 Benchmark 的 minicodex_summary.json")
    parser.add_argument("--minimum-runs", type=int, default=3,
                        help="发布所需最少重复次数（默认：3）")
    parser.add_argument("--skip-local", action="store_true",
                        help="跳过 compileall、pytest 与确定性 HarnessBench")
    parser.add_argument("--allow-other-commit", action="store_true",
                        help="允许报告来自非当前 Git commit；正式发布不建议使用")
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if args.minimum_runs < 1:
        raise SystemExit("--minimum-runs 必须为正数")
    failures = [] if args.skip_local else _run_local_checks()
    if args.summary is None:
        failures.append(GateFailure("online_benchmark", "提供完整 Benchmark summary", None))
    else:
        try:
            document = json.loads(args.summary.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(GateFailure("summary", "可读取的 JSON", str(exc)))
        else:
            report = evaluate_summary(
                document,
                policy=ReleasePolicy(minimum_runs=args.minimum_runs),
                expected_git_head=None if args.allow_other_commit else _git_head(),
            )
            failures.extend(report.failures)
    if failures:
        print("RELEASE GATE: FAILED")
        for failure in failures:
            print(f"- {failure.check}: expected {failure.expected}; actual {failure.actual!r}")
        raise SystemExit(1)
    print("RELEASE GATE: PASSED")


if __name__ == "__main__":
    main()
