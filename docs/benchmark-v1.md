# MiniCodex Benchmark V1

`minicodex-bench-v1` is the fixed, opt-in repository coding benchmark used to
compare a credible simple baseline with the current MiniCodex control plane.
It reuses `EvaluationHarness`, `EvaluationCheckRunner`, runtime traces, and
`ExecutionMetrics`; it is not a second evaluation framework.

## Catalog

The catalog contains 30 unique tasks: 5 create, 7 modify, 8 fix, 4 refactor,
2 dependency/environment, 2 follow-up, and 2 already-satisfied tasks. It covers
Python packages, Flask, FastAPI, HTML/JavaScript, and TypeScript-compatible
modules. `smoke_fixtures()` selects eight stable representative cases.

Every case has a hidden executable Python/pytest oracle. Fixture source is placed in an isolated
agent workspace. Oracle files live in a separate root, are not materialized
until the agent has terminated, and are removed immediately after the check so
later agents cannot discover prior oracles. Workspace file tools reject path traversal; the
evaluation runner alone receives both roots. Oracles execute behavior wherever
possible. Structural assertions are used only when structure or dependency
metadata is itself part of the requirement.

## Metric definitions

- Task success requires the independent oracle, the normal completion gate,
  budgets, and an error-free run.
- First-pass success requires the first post-edit validation whose purpose is
  `ACCEPTANCE` and scope is `TARGETED` to pass on the final edit revision. The
  independent oracle must pass, with no repair/recovery or rollback. A
  regression-only or full-suite pass does not qualify. Explicit
  already-satisfied cases are excluded from this rate's denominator.
- Recovery is entered when a failed/inconclusive post-edit validation is
  followed by a corrective edit, or the existing repair path records an
  attempt. Recovery succeeds only when corrective action occurred and the final
  independent oracle passes. Non-recovery tasks are excluded from the rate.
- Validation pass rate is `passed / (passed + failed)`; inconclusive executions
  are reported separately.
- False completion means a successful agent terminal outcome followed by an
  independent oracle failure.
- Unauthorized edit means an inspect-only or informational task changed a
  file. Wrong-file edit is separate: a modify task touched only paths outside
  its fixture's deterministic expected implementation scope. Ambiguous cases
  leave strict wrong-file detection disabled, and allowed supporting edits do
  not become false positives.
- A failed tool call is a canonical tool result with `success == false`, such
  as malformed arguments, an execution exception, or a policy block. A
  validator that executes successfully but reports failing tests remains a
  successful tool call and a failed validation outcome.
- Agent steps are main loop turns. They are distinct from tool calls and all
  LLM calls.
- Cost remains `null` unless a provider reports trustworthy pricing data.

The raw schema also records action economy, validation counts, recovery,
rollbacks, wrong targets, repetition, token use, call classes, latency, oracle
checks, failure category/reason, trace path, profile, run index, and benchmark
version. Summaries report aggregate and per-category metrics. Failure reports
group deterministic categories without an LLM judge.

## Profiles and fairness

Both profiles use the shared `MiniCodexAgent` loop, identical fixtures, model,
temperature, maximum main-loop steps, timeout class, tools, and oracle.
`minicodex` uses the normal mode policy. `baseline` remains able to inspect,
edit, run commands/tests, and validate, but disables planning/replanning,
long-term-memory policy, and heavy recovery. The comparison report never assumes
that MiniCodex improves a metric.

## Live CLI

Live execution requires explicit provider, model, and credential configuration:

Before any model is constructed or task starts, the CLI checks the environment
needed by the selected fixtures. Python and pytest are always checked; FastAPI,
Flask, packaging, node, and npm are checked only when selected cases require
them. A failed preflight exits with status 2 and emits no benchmark results.
Successful preflight details are stored under `metadata.environment`. Run the
same check without credentials or provider calls with:

```bash
python -m minicodex.evaluation.run_benchmark --profile both --smoke --preflight-only
```

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

Useful filters are `--category`, repeatable `--case-id`, `--max-steps`,
`--temperature`, `--base-url`, and `--output`. Non-DeepSeek provider labels
require an explicit compatible `--base-url`. Results are written beneath:

```text
benchmark_results/minicodex-bench-v1/<experiment-id>/
├── baseline/run_001.jsonl
├── minicodex/run_001.jsonl
├── traces/...
└── summaries/
    ├── baseline_summary.json
    ├── minicodex_summary.json
    ├── *_failures.json
    └── comparison.json
```

Existing experiment directories and raw run files are never overwritten.
Ordinary `python -m pytest` does not invoke this CLI or a live provider.
