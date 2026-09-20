"""Explicit opt-in CLI for MiniCodex Benchmark V1."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from .benchmark_v1 import BENCHMARK_VERSION, catalog_by_id, fixtures, smoke_fixtures
from .harness import EvaluationHarness
from .models import EvaluationSummary
from .profiles import EvaluationProfile, benchmark_policy
from .preflight import benchmark_preflight
from .reporting import (
    compare_profiles,
    comparison_markdown,
    failure_clusters,
    failure_markdown,
    summary_markdown,
    write_jsonl,
)
from ..agent.routing import TaskRouter
from ..llm.client import LLMClient
from ..main import APPLICATION_ROOT, build_agent
from ..workspace import WorkspaceConfig


def _git_head() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=APPLICATION_ROOT, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _metadata(args, *, profile: str, task_count: int, timestamp: str, environment=None) -> dict:
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "timestamp": timestamp,
        "git_head": _git_head(),
        "profile": profile,
        "provider": args.provider,
        "model": args.model,
        "model_parameters": {"temperature": args.temperature},
        "max_steps": args.max_steps,
        "runs": args.runs,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "task_count": task_count,
        "environment": environment,
    }


def _select(args):
    selected = list(smoke_fixtures() if args.smoke else fixtures())
    if args.category:
        selected = [fixture for fixture in selected if fixture.case.category == args.category]
    if args.case_id:
        requested = set(args.case_id)
        known = catalog_by_id()
        missing = requested - set(known)
        if missing:
            raise ValueError(f"未知用例 ID：{', '.join(sorted(missing))}")
        selected = [fixture for fixture in selected if fixture.case.case_id in requested]
    return selected


def _materialize(files, root: Path) -> None:
    for relative, content in files:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _cleanup_oracle(root: Path) -> None:
    if root.is_dir() and root.parent.name == "oracles":
        shutil.rmtree(root)


def _run_profile(args, *, selected, profile: EvaluationProfile, experiment_root: Path,
                 timestamp: str, api_key: str, preflight) -> EvaluationSummary:
    all_results = []
    for run_index in range(1, args.runs + 1):
        run_root = experiment_root / profile.value / f"run_{run_index:03d}"
        trace_root = experiment_root / "traces" / profile.value / f"run_{run_index:03d}"
        by_id = {fixture.case.case_id: fixture for fixture in selected}

        def factory(case):
            fixture = by_id[case.case_id]
            workspace = run_root / "workspaces" / case.case_id
            oracle = run_root / "oracles" / case.case_id
            workspace.mkdir(parents=True, exist_ok=False)
            _materialize(fixture.workspace_files, workspace)
            llm = LLMClient(api_key=api_key, base_url=args.base_url, model=args.model,
                            temperature=args.temperature)
            agent, recorder, _memory = build_agent(
                WorkspaceConfig.create(workspace, application_root=APPLICATION_ROOT),
                llm=llm, control_llm=llm, judge_llm=llm, output_level=args.output_level,
            )
            agent.max_steps = args.max_steps
            agent.configured_max_steps = args.max_steps
            agent.task_max_steps = args.max_steps
            route = TaskRouter().route(case.prompt)
            agent._benchmark_policy = benchmark_policy(
                profile, mode=route.mode, max_steps=args.max_steps,
                needs_plan=getattr(route, "needs_plan", None),
            )
            agent._benchmark_oracle_root = oracle
            agent._benchmark_materialize_oracle = lambda: _materialize(fixture.oracle_files, oracle)
            agent._benchmark_cleanup_oracle = lambda: _cleanup_oracle(oracle)
            agent._benchmark_recorder = recorder
            trace_path = trace_root / f"{case.case_id}.jsonl"
            agent._benchmark_trace_path = str(trace_path)
            return agent

        harness = EvaluationHarness(
            agent_factory=factory,
            profile=profile.value,
            model=args.model,
            run_index=run_index,
        )
        summary = harness.run_suite(
            run_name=f"{BENCHMARK_VERSION}:{profile.value}:run_{run_index:03d}",
            cases=[fixture.case for fixture in selected],
        )
        raw_path = experiment_root / profile.value / f"run_{run_index:03d}.jsonl"
        write_jsonl(raw_path, summary.results)
        all_results.extend(summary.results)

    metadata = _metadata(
        args,
        profile=profile.value,
        task_count=len(selected),
        timestamp=timestamp,
        environment=preflight.to_dict(),
    )
    return EvaluationSummary(
        run_name=f"{BENCHMARK_VERSION}:{profile.value}",
        results=all_results,
        metadata=metadata,
    )


def _save_profile(summary: EvaluationSummary, experiment_root: Path) -> None:
    profile = summary.metadata["profile"]
    summary_path = experiment_root / "summaries" / f"{profile}_summary.json"
    summary.save_json(summary_path)
    (experiment_root / "summaries" / f"{profile}_summary.md").write_text(
        summary_markdown(summary), encoding="utf-8"
    )
    (experiment_root / "summaries" / f"{profile}_failures.json").write_text(
        json.dumps(failure_clusters(summary.results), indent=2), encoding="utf-8"
    )
    (experiment_root / "summaries" / f"{profile}_failures.md").write_text(
        failure_markdown(summary.results), encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行可选的 MiniCodex Benchmark V1")
    parser.add_argument("--profile", choices=("baseline", "minicodex", "both"), required=True,
                        help="评测配置：baseline、minicodex，或同时运行两者。")
    parser.add_argument("--provider",
                        help="记录用的提供商标签；不会仅根据 .env 推断并启动在线执行。")
    parser.add_argument("--model", help="模型名称。")
    parser.add_argument("--base-url", help="非 DeepSeek 提供商所需的 API Base URL。")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY",
                        help="存放 API 密钥的环境变量名。")
    parser.add_argument("--temperature", type=float, default=0.0, help="采样温度。")
    parser.add_argument("--max-steps", type=int, default=20, help="每个任务的最大主循环步数。")
    parser.add_argument("--runs", type=int, default=1, help="每个配置的重复运行次数。")
    parser.add_argument("--smoke", action="store_true", help="仅运行冒烟用例子集。")
    parser.add_argument("--category", choices=("create", "modify", "fix", "refactor", "dependency",
                                                "follow_up", "already_satisfied"),
                        help="按用例类别过滤。")
    parser.add_argument("--case-id", action="append", default=[], help="按用例 ID 过滤（可重复指定）。")
    parser.add_argument("--output", type=Path, default=Path("benchmark_results"),
                        help="评测结果输出根目录。")
    parser.add_argument("--experiment-id", help="实验 ID；默认使用 UTC 时间戳。")
    parser.add_argument("--output-level", choices=("normal", "verbose", "debug"), default="normal",
                        help="Agent 输出详细程度。")
    parser.add_argument("--preflight-only", action="store_true",
                        help="仅校验所选用例所需基础设施，不使用凭证、不调用模型。")
    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.runs < 1 or args.max_steps < 1:
        parser.error("--runs 与 --max-steps 必须为正数")
    try:
        selected = _select(args)
    except ValueError as exc:
        parser.error(str(exc))
    if not selected:
        parser.error("没有匹配当前筛选条件的基准用例")
    preflight = benchmark_preflight(selected)
    print(preflight.render())
    if not preflight.ready:
        raise SystemExit(2)
    if args.preflight_only:
        return
    if not args.provider or not args.model:
        parser.error("在线基准评测需要显式指定 --provider 与 --model")
    if args.provider.lower() != "deepseek" and not args.base_url:
        parser.error("非 DeepSeek 提供商需要显式指定 --base-url")
    api_key = os.getenv(args.api_key_env, "").strip()
    if not api_key:
        parser.error(f"在线基准评测需要在环境变量 {args.api_key_env} 中提供 API 凭证")

    timestamp = datetime.now(timezone.utc).isoformat()
    experiment_id = args.experiment_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    experiment_root = args.output / BENCHMARK_VERSION / experiment_id
    if experiment_root.exists():
        parser.error(f"实验输出目录已存在：{experiment_root}")
    (experiment_root / "summaries").mkdir(parents=True)

    profiles = ([EvaluationProfile.BASELINE, EvaluationProfile.MINICODEX]
                if args.profile == "both" else [EvaluationProfile(args.profile)])
    summaries = {}
    for profile in profiles:
        summary = _run_profile(args, selected=selected, profile=profile,
                               experiment_root=experiment_root, timestamp=timestamp, api_key=api_key,
                               preflight=preflight)
        _save_profile(summary, experiment_root)
        summaries[profile.value] = summary

    if len(summaries) == 2:
        comparison = compare_profiles(summaries["baseline"], summaries["minicodex"])
        (experiment_root / "summaries" / "comparison.json").write_text(
            json.dumps(comparison, indent=2), encoding="utf-8"
        )
        (experiment_root / "summaries" / "comparison.md").write_text(
            comparison_markdown(comparison), encoding="utf-8"
        )
    print(experiment_root)


if __name__ == "__main__":
    main()
