"""Machine-readable and human-readable Benchmark V1 reports."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics

from .models import EvaluationResult, EvaluationSummary


COMPARISON_METRICS = (
    "task_success_rate",
    "first_pass_success_rate",
    "false_completion_rate",
    "average_tool_calls",
    "average_steps",
    "average_llm_calls",
    "recovery_success_rate",
    "max_step_exhaustion_rate",
    "median_tokens_per_success",
    "median_latency_per_success_seconds",
)


def write_jsonl(path: str | Path, results: list[EvaluationResult]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")


def failure_clusters(results: list[EvaluationResult]) -> dict:
    failed = [result for result in results if not result.passed]
    grouped = defaultdict(list)
    for result in failed:
        grouped[result.failure_category or "unknown"].append({
            "case_id": result.case_id,
            "run_index": result.run_index,
            "reason": result.failure_reason,
            "agent_steps": result.agent_steps,
            "tool_calls": result.tool_call_count,
            "llm_calls": result.llm_call_count,
            "trace_path": result.trace_path,
        })
    return {
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "counts": dict(sorted(Counter(result.failure_category or "unknown" for result in failed).items())),
        "clusters": dict(sorted(grouped.items())),
    }


def compare_profiles(baseline: EvaluationSummary, minicodex: EvaluationSummary) -> dict:
    before, after = baseline.vibe_metrics(), minicodex.vibe_metrics()
    metrics = {}
    for name in COMPARISON_METRICS:
        left, right = before.get(name), after.get(name)
        metrics[name] = {
            "baseline": left,
            "minicodex": right,
            "delta": right - left if left is not None and right is not None else None,
        }

    def probabilities(summary):
        values = defaultdict(list)
        for result in summary.results:
            values[result.case_id].append(bool(result.passed))
        return {case_id: statistics.fmean(outcomes) for case_id, outcomes in values.items()}

    base_probability, mini_probability = probabilities(baseline), probabilities(minicodex)
    common = sorted(set(base_probability) & set(mini_probability))
    improved = [case_id for case_id in common if mini_probability[case_id] > base_probability[case_id]]
    regressed = [case_id for case_id in common if mini_probability[case_id] < base_probability[case_id]]
    unchanged = [case_id for case_id in common if mini_probability[case_id] == base_probability[case_id]]
    return {
        "benchmark_version": baseline.metadata.get("benchmark_version"),
        "baseline_run": baseline.run_name,
        "minicodex_run": minicodex.run_name,
        "metrics": metrics,
        "improved_cases": improved,
        "regressed_cases": regressed,
        "unchanged_cases": unchanged,
    }


def summary_markdown(summary: EvaluationSummary) -> str:
    metrics = summary.vibe_metrics()
    lines = [f"# {summary.run_name}", "", f"Cases: {summary.total_cases}", "", "| Metric | Value |", "|---|---:|"]
    for name, value in metrics.items():
        lines.append(f"| {name} | {value if value is not None else 'n/a'} |")
    failures = failure_clusters(summary.results)
    lines.extend(["", "## Failure clusters", ""])
    if not failures["counts"]:
        lines.append("No failures.")
    else:
        for category, count in failures["counts"].items():
            lines.append(f"- {category}: {count}")
    return "\n".join(lines) + "\n"


def failure_markdown(results: list[EvaluationResult]) -> str:
    report = failure_clusters(results)
    lines = ["# Failure report", "", f"{report['total']} tasks/runs; {report['passed']} passed; {report['failed']} failed."]
    for category, cases in report["clusters"].items():
        lines.extend(["", f"## {category} ({len(cases)})", ""])
        for case in cases:
            trace = case["trace_path"] or "n/a"
            lines.append(
                f"- {case['case_id']} run {case['run_index']}: {case['reason']} "
                f"(steps={case['agent_steps']}, tools={case['tool_calls']}, "
                f"llm={case['llm_calls']}, trace={trace})"
            )
    if not report["clusters"]:
        lines.extend(["", "No failures."])
    return "\n".join(lines) + "\n"


def comparison_markdown(comparison: dict) -> str:
    lines = ["# Baseline vs MiniCodex", "", "| Metric | Baseline | MiniCodex | Delta |", "|---|---:|---:|---:|"]
    for name, values in comparison["metrics"].items():
        lines.append(f"| {name} | {values['baseline']} | {values['minicodex']} | {values['delta']} |")
    for label in ("improved_cases", "regressed_cases", "unchanged_cases"):
        lines.extend(["", f"## {label.replace('_', ' ').title()}", "",
                      ", ".join(comparison[label]) or "None"])
    return "\n".join(lines) + "\n"
