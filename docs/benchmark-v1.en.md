# MiniCodex Benchmark V1

[简体中文](benchmark-v1.md) · **English**

`minicodex-bench-v1-r2` is a fixed, explicitly opt-in repository coding benchmark for comparing a credible simple baseline with the current MiniCodex control plane. R2 corrected overly narrow oracles that rejected standard TypeScript annotations, `querySelector`, and DOM `onclick` usage. It reuses `EvaluationHarness`, `EvaluationCheckRunner`, runtime traces, and `ExecutionMetrics`; it is **not** a second evaluation framework.

## Task catalog

The catalog contains 30 non-duplicate tasks: five create, seven modify, eight fix, four refactor, two dependency/environment, two follow-up, and two already-satisfied cases. It covers Python packages, Flask, FastAPI, HTML/JavaScript, and TypeScript-compatible modules. `smoke_fixtures()` selects eight stable representative cases.

Every case has a hidden executable Python or pytest oracle. Fixture source lives in an isolated agent workspace. Oracle files live under a separate root and are materialized only after the agent exits, then deleted immediately after evaluation so later agents cannot discover historical oracles. Workspace file tools reject path traversal; only the evaluation runner holds both roots. Behavioral oracles are preferred whenever behavior can be executed. Structural assertions are used only when structure or dependency metadata is itself part of the requirement.

## Metric definitions

- **Task success**: the independent oracle passes, the normal completion gate passes, budget is not exhausted, and the run has no error.
- **First-edit success**: on the final edit revision, the first post-edit validation with purpose `ACCEPTANCE` and scope `TARGETED` passes; the independent oracle also passes; no repair/recovery or rollback occurs. A regression or full-suite pass alone does not count. Explicit already-satisfied cases are excluded from the denominator.
- **Recovery**: entered when a corrective edit follows failed or inconclusive post-edit validation, or when an existing repair path records an attempt. Recovery succeeds only after a real corrective action and a passing independent oracle. Tasks that never enter recovery are excluded from the denominator.
- **Validation pass rate**: `passed / (passed + failed)`; inconclusive outcomes are reported separately.
- **False completion**: the agent reports terminal success while the independent oracle fails.
- **Unauthorized edit**: an inspect-only or informational task changes a file. **Wrong-file edit** is separate: a modify task changes a path outside the fixture's deterministic expected implementation scope. Strict wrong-file detection is disabled for semantically ambiguous cases; explicitly allowed support edits are not false positives.
- **Failed tool call**: a normalized tool result has `success == false`, such as malformed arguments, an execution exception, or a policy block. A validator that executes correctly but reports a failed test is a **successful tool call** plus a **failed validation result**.
- **Agent step**: one main-loop turn, distinct from tool-call count and total LLM-call count.
- **Cost**: remains `null` unless the provider supplies trustworthy pricing data.

The raw schema also records action economy, validation counts, recovery, rollback, wrong targets, repetition, token usage, call classes, latency, oracle checks, failure category/reason, trace path, profile, run index, and benchmark version. Summary reports provide overall and per-category metrics. Failure reports use deterministic clustering, never an LLM judge.

## Profiles and fairness

Both profiles share the same `MiniCodexAgent` loop, fixtures, model, temperature, maximum main-loop steps, timeout classes, tools, and oracles. The `minicodex` profile uses normal-mode policy. The `baseline` can still inspect, edit, run commands/tests, and validate, but disables planning/replanning, long-term-memory policy, and deep recovery. Comparison reports **never assume** MiniCodex must improve a metric.

## Online CLI

Online execution requires an explicit provider, model, and credentials.

Before constructing a model or starting a task, the CLI checks the environment required by the selected fixtures. Python and pytest are always checked. FastAPI, Flask, packaging, node, and npm are checked only when selected cases need them. A failed preflight exits with code 2 and writes no benchmark result. Successful details are stored in `metadata.environment`. Preflight can run without credentials or provider calls:

```bash
python -m minicodex.evaluation.run_benchmark --profile both --smoke --preflight-only
```

Example runs:

```bash
python -m minicodex.evaluation.run_benchmark \
  --profile minicodex --provider deepseek --model deepseek-chat --runs 1

python -m minicodex.evaluation.run_benchmark \
  --profile baseline --provider deepseek --model deepseek-chat --runs 3

python -m minicodex.evaluation.run_benchmark \
  --profile both --provider deepseek --model deepseek-chat --runs 3

python -m minicodex.evaluation.run_benchmark \
  --profile minicodex --provider deepseek --model deepseek-chat --smoke
```

Common filters include `--category`, repeatable `--case-id`, `--max-steps`, `--temperature`, `--base-url`, and `--output`. A non-DeepSeek provider label requires an explicit compatible `--base-url`.

Results are written under:

```text
benchmark_results/minicodex-bench-v1-r2/<experiment-id>/
├── baseline/run_001.jsonl
├── minicodex/run_001.jsonl
├── traces/...
└── summaries/
    ├── baseline_summary.json
    ├── minicodex_summary.json
    ├── *_failures.json
    └── comparison.json
```

Existing experiment directories and raw run files are **never overwritten**. Ordinary `python -m pytest` does **not** invoke this CLI or make online provider requests.

## Release gate and real-repository dogfooding

First run a single task against an isolated copy of a real repository, then manually inspect its diff, test result, and trace:

```bash
minicodex run "Implement a bounded, verifiable real requirement" \
  --workspace /path/to/repository-copy \
  --output verbose
```

After generating a complete 30-task online report, run the release gate:

```bash
python -m minicodex.evaluation.release_gate \
  --summary benchmark_results/minicodex-bench-v1-r2/<experiment-id>/summaries/minicodex_summary.json
```

The default gate first runs `compileall`, full pytest, and deterministic HarnessBench. It then requires an online report from the current Git commit with all 30 tasks repeated at least three times, 100% success, and zero critical safety errors. `--minimum-runs 1` is only for candidate diagnosis and is not the formal release standard.
