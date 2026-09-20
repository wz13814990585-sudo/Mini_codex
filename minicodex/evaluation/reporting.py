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
    "recovery_success_rate",
    "validation_pass_rate",
    "average_steps",
    "median_steps",
    "average_tool_calls",
    "median_tool_calls",
    "average_failed_tool_calls",
    "failed_tool_call_rate",
    "average_llm_calls",
    "false_completion_rate",
    "max_step_exhaustion_rate",
    "unauthorized_edit_rate",
    "wrong_file_edit_rate",
    "wrong_validation_target_rate",
    "repeated_tool_rate",
    "average_tokens",
    "median_tokens_per_success",
    "average_latency_seconds",
    "median_latency_per_success_seconds",
)

# Human-facing Markdown labels only. JSON / machine keys stay English.
METRIC_LABELS_ZH = {
    "task_success_rate": "任务成功率",
    "task_success_rate_stddev": "任务成功率标准差",
    "first_pass_success_rate": "首次修改成功率",
    "false_completion_rate": "误报完成率",
    "recovery_success_rate": "恢复成功率",
    "validation_pass_rate": "验证通过率",
    "validation_inconclusive": "验证不确定次数",
    "max_step_exhaustion_rate": "步数耗尽率",
    "wrong_validation_target_rate": "错误验证目标率",
    "unauthorized_edit_count": "未授权编辑次数",
    "unauthorized_edit_rate": "未授权编辑率",
    "wrong_file_edit_count": "错误文件编辑次数",
    "wrong_file_edit_rate": "错误文件编辑率",
    "average_tool_calls": "平均工具调用次数",
    "median_tool_calls": "工具调用次数中位数",
    "average_failed_tool_calls": "平均失败工具调用次数",
    "failed_tool_call_rate": "工具调用失败率",
    "tool_calls_per_success": "每次成功的工具调用数",
    "average_steps": "平均步数",
    "median_steps": "步数中位数",
    "average_llm_calls": "平均 LLM 调用次数",
    "llm_calls_per_success": "每次成功的 LLM 调用数",
    "median_time_to_success": "成功耗时中位数",
    "median_tokens_per_success": "成功任务 token 中位数",
    "median_cost_per_success_usd": "成功任务成本中位数（美元）",
    "main_llm_calls_per_success": "每次成功的主 LLM 调用数",
    "control_llm_calls_per_success": "每次成功的控制 LLM 调用数",
    "median_time_to_first_edit": "首次编辑耗时中位数",
    "average_inspections_before_first_edit": "首次编辑前平均检查次数",
    "repeated_tool_rate": "重复工具调用率",
    "rollback_rate": "回滚率",
    "average_tokens": "平均 token 数",
    "total_tokens": "总 token 数",
    "average_latency_seconds": "平均延迟（秒）",
    "median_latency_per_success_seconds": "成功任务延迟中位数（秒）",
    "cost_per_success_usd": "每次成功成本（美元）",
}

CASE_GROUP_LABELS_ZH = {
    "improved_cases": "改善用例",
    "regressed_cases": "回退用例",
    "unchanged_cases": "无变化用例",
}


def _metric_label(name: str) -> str:
    return METRIC_LABELS_ZH.get(name, name)


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
    lines = [
        f"# {summary.run_name}",
        "",
        f"用例数：{summary.total_cases}",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
    ]
    for name, value in metrics.items():
        lines.append(f"| {_metric_label(name)} | {value if value is not None else '不适用'} |")
    failures = failure_clusters(summary.results)
    lines.extend(["", "## 失败聚类", ""])
    if not failures["counts"]:
        lines.append("无失败。")
    else:
        for category, count in failures["counts"].items():
            lines.append(f"- {category}: {count}")
    return "\n".join(lines) + "\n"


def failure_markdown(results: list[EvaluationResult]) -> str:
    report = failure_clusters(results)
    lines = [
        "# 失败报告",
        "",
        f"共 {report['total']} 次任务/运行；{report['passed']} 次通过；{report['failed']} 次失败。",
    ]
    for category, cases in report["clusters"].items():
        lines.extend(["", f"## {category} ({len(cases)})", ""])
        for case in cases:
            trace = case["trace_path"] or "不适用"
            lines.append(
                f"- {case['case_id']} 运行 {case['run_index']}: {case['reason']} "
                f"（步数={case['agent_steps']}，工具={case['tool_calls']}，"
                f"llm={case['llm_calls']}，trace={trace}）"
            )
    if not report["clusters"]:
        lines.extend(["", "无失败。"])
    return "\n".join(lines) + "\n"


def comparison_markdown(comparison: dict) -> str:
    lines = [
        "# Baseline 与 MiniCodex 对比",
        "",
        "| 指标 | Baseline | MiniCodex | 变化 |",
        "|---|---:|---:|---:|",
    ]
    for name, values in comparison["metrics"].items():
        lines.append(
            f"| {_metric_label(name)} | {values['baseline']} | {values['minicodex']} | {values['delta']} |"
        )
    for key in ("improved_cases", "regressed_cases", "unchanged_cases"):
        label = CASE_GROUP_LABELS_ZH[key]
        lines.extend(["", f"## {label}", "",
                      ", ".join(comparison[key]) or "无"])
    return "\n".join(lines) + "\n"
