# MiniCodex

[简体中文](README.md) · **English**

[![CI](https://github.com/wz13814990585-sudo/Mini_codex/actions/workflows/ci.yml/badge.svg)](https://github.com/wz13814990585-sudo/Mini_codex/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/)
[![Release](https://img.shields.io/github/v/release/wz13814990585-sudo/Mini_codex)](https://github.com/wz13814990585-sudo/Mini_codex/releases/latest)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

MiniCodex is a **CLI-first local AI coding agent**. Give it a natural-language task and it inspects the repository, edits code, and runs relevant checks. With `--review`, it also shows the resulting diff in the terminal for a human to accept or reject. It supports DeepSeek and other OpenAI Chat Completions-compatible models. The Web workspace is optional; both interfaces use the same runtime.

Its central boundary is: **the model handles understanding and decisions; the deterministic Harness owns facts, permissions, safety, execution, validation, recovery, and final completion.** A model message saying “done” can never finish a modification task by itself.

> Current source version: `0.4.2.dev0`; the latest packaged release is still [`v0.4.1`](https://github.com/wz13814990585-sudo/Mini_codex/releases/tag/v0.4.1). Install from source for the CLI review and editor features described below. This is an Alpha project: try it only in a trusted, committed or backed-up workspace.

This README addresses three reproducible questions: Can the agent change a real repository? What evidence lets it call a task complete? How can a user inspect and undo its edits? The demo, architecture, and test sections answer these questions; the [architecture guide](docs/architecture.en.md) and [benchmark guide](docs/benchmark-v1.en.md) cover implementation details.

## Why MiniCodex

| Capability | Implementation | User value |
| --- | --- | --- |
| Repository-level coding | Repository map, symbol index, relevant paths, and test targeting | Locates and edits code in real projects instead of generating isolated snippets |
| Evidence-based completion | Typed validation contracts, a revision-aware evidence ledger, and an independent completion gate | Does not treat the model's “done” message as validation |
| Safe editing | Workspace boundaries, safety policy, checkpoints, and concurrent-change detection | Limits file scope and avoids overwriting external changes during rollback |
| Bounded recovery | Failure classification, rereads, retries, replanning, and rollback | Recovers from stale context and failed tests without unbounded loops |
| Observable execution | JSONL traces, token/call metrics, and structured task reports | Makes it possible to inspect why the agent read, edited, validated, or stopped |
| Repeatable evaluation | 30 isolated tasks, hidden oracles, baseline comparison, and a release gate | Separates passing code tests from real-model task success |

## Product flow

```text
Natural-language task
    ↓
Semantic routing and requirement extraction
    ↓
Inspect repository → plan when needed → controlled edits
    ↓
Targeted acceptance → related regression → fix / recover
    ↓
Deterministic completion gate → structured report → optional human diff review / accept or reject
```

The runtime has one control-plane source of truth: `TaskRuntime.state`.

```text
Workspace / tool facts → RuntimeEvent → TaskState → context → model action
                             ↑                    ↓
                             └── safe execution and validation ──┘
```

## Quick start

### Requirements

- Python 3.11 or newer
- A DeepSeek API key, or another OpenAI Chat Completions-compatible model service
- Git (recommended for status and diff inspection)

### 1. Install

Install from source:

```bash
git clone https://github.com/wz13814990585-sudo/Mini_codex.git
cd Mini_codex
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Install from source to reproduce the current features described here. For development and tests, install:

```bash
python -m pip install -e ".[test]"
```

### 2. Configure a model

```bash
cp .env.example .env
```

```dotenv
MINICODEX_API_KEY=your_api_key_here
MINICODEX_BASE_URL=https://api.deepseek.com
MINICODEX_MODEL=deepseek-chat
```

MiniCodex reads `.env` from the launch directory. Existing `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_MODEL` variables remain supported. `--model` and `--base-url` override environment configuration. API keys are read only from environment variables so they do not appear in shell history.

### 3. Check the environment

```bash
minicodex doctor
```

Plain `doctor` stays offline. The following command sends one minimal model request and may incur a small charge:

```bash
minicodex doctor --connect
```

Scripts and CI can consume JSON:

```bash
minicodex doctor --json
```

### 4. Run a CLI task

Start with an isolated test repository and use `--review` to inspect the diff:

```bash
minicodex run "Fix email validation in the registration endpoint and run the relevant tests" \
  --workspace /path/to/project \
  --review
```

At the prompt, enter `accept` to keep the edits or `reject` to undo this task's checkpointed Agent edits. Rejection does not reset the Git repository. MiniCodex refuses to overwrite a file changed by another program after the Agent's edit. Interrupting review leaves the files for manual resolution.

For a continuing conversation, run:

```bash
minicodex chat --workspace /path/to/project --review
```

Omit `--review` for non-interactive scripts. Running without a subcommand still opens the compatible interactive mode, and the legacy `--prompt` entry point remains available. Traces are stored locally by workspace.

### 5. Optional: local Web workspace

```bash
minicodex ui --workspace /path/to/project
```

The optional workspace provides a file tree, code editor, interactive terminal, Agent chat, traces, diffs, and Accept / Reject; panes are resizable. It has no language server, debugger, or extension system and is not a full IDE. Its terminal runs as your OS user and **does not inherit the Agent tool safety policy**. Use it only in trusted workspaces. See the [UI guide](docs/ui.en.md) for details and safety notes.

## CLI reference

| Command | Purpose | Model access |
| --- | --- | --- |
| `minicodex run "task"` | Execute one task and exit; optional `--review` shows the diff | Yes |
| `minicodex chat` | Start a continuous interactive session; optional `--review` after each task | Yes |
| `minicodex doctor` | Check Python, workspace, Git, and model configuration | No |
| `minicodex doctor --connect` | Also verify a real model connection | Yes, one minimal request |
| `minicodex ui` | Start the optional Web workspace; tasks use the same runtime | No at startup; yes when a task runs |
| `minicodex --version` | Print the version | No |
| `minicodex-release-gate --summary ...` | Check local regressions and an online Benchmark report | Reads the report by default |

Common options:

- `--workspace / -w`: target repository; defaults to the current directory
- `--output`: `normal`, `verbose`, or `debug`
- `--model`: override the model name
- `--base-url`: override the compatible API endpoint
- `--api-key-env`: read the key from a named environment variable

## Five-minute demo

The repository includes a small calculator project with a deliberate missing edge case. Copy it before running the agent so the source example stays unchanged:

```bash
demo_dir="$(mktemp -d)/calculator_demo"
cp -R examples/calculator_demo "$demo_dir"

minicodex run \
  "Update src/calculator.py so divide(a, b) raises ValueError when b is zero, add a regression test to tests/test_calculator.py, and run the tests." \
  --workspace "$demo_dir" \
  --review

python -m pytest -q "$demo_dir/tests"
```

Choose `accept` at the review prompt before running the final test command. This flow demonstrates repository inspection, editing, targeted checks, a diff, and human confirmation. Real-model output can vary by model and environment. See the [calculator demo](examples/calculator_demo/README.en.md) for details.

## Supported workflows

- Informational questions and read-only code review
- Entering tasks, reviewing the Agent diff, and accepting or rejecting checkpointed edits in the terminal
- Browsing files, reviewing code and diffs, tracking tasks, and Accept / Reject through the local Web UI
- Human-in-the-loop approval in the Web UI before caution-level operations execute
- Creating, modifying, fixing, and refactoring Python, JavaScript, TypeScript, and HTML projects
- Running commands, pytest, and project test scripts
- Validating Flask and FastAPI endpoints
- Static Web validation and optional Playwright browser interaction checks
- Detecting missing Python dependencies and installing them through a controlled tool
- Git status, diff inspection, and task-level undo infrastructure

The Harness selects an execution mode from task semantics:

- `FAST`: small edits and minimum sufficient validation
- `STANDARD`: repository inspection, optional planning, acceptance, and related regression
- `COMPLEX`: multi-step edits, iterative validation, and broader regression
- `INSPECT_ONLY`: read-only inspection with no edit tools
- `INFORMATIONAL`: direct answers without entering the coding loop

## Validation, safety, and recovery

Each requirement becomes an independent `ValidationCheck`, then binds to a file, test, command, HTTP, browser, or semantic contract. `ValidatorResolver` chooses a validator only from the contract and registered capabilities. `ValidationLedger` stores revision-aware evidence. `TaskCompletionPolicy` permits success only when every required check has proof for the current revision.

New filenames, exact text, or DOM states suggested only by the control model are not promoted to hard acceptance checks unless grounded in the user's request or existing repository. The original user goal remains a semantic check instead. Semantic validation can be inconclusive; MiniCodex reports that honestly rather than claiming runtime behavior was proven.

Important boundaries:

- Read-only tasks never receive editing or dependency-install capabilities.
- File, command, and dependency operations pass through safety and workspace checks.
- Commands have timeout, output, file-size, CPU, and memory limits.
- `run_command` blocks common heredoc, inline-file-write, and redirection bypasses; the process sandbox **does not isolate the filesystem**, so run it only in a trusted local workspace.
- Checkpoints cover only agent-owned edits; rollback refuses to overwrite concurrent external changes.
- Static HTML checks cannot substitute for click, keyboard, or runtime-state validation.
- Missing required capabilities or reliable targets produce an explicit blocker, not fabricated success.
- A passing test, successful tool call, or model completion claim cannot close the whole task by itself.

See the [architecture guide](docs/architecture.en.md) and [Validation Core V2](docs/validation-core-v2.en.md) for details.

## Observability and local data

Runtime data is isolated per repository under the user directory and never written into the target project:

```text
~/.minicodex/workspaces/<repository-key>/
├── memory/long_term.json   # cross-task experience
├── traces/latest.jsonl     # latest structured trace
└── sandbox/                # sandbox runtime data
```

`normal` shows primary results. `verbose` adds execution and phase details. `debug` also exposes internal result identifiers, trace summaries, and long-term-memory statistics. Long-term memory is only a cache; the physical workspace always remains authoritative.

## Project structure

```text
minicodex/
├── main.py                 # CLI composition root and agent construction
├── doctor.py               # environment and model configuration diagnostics
├── llm/                    # provider configuration, client, and response types
├── prompts/                # system prompts
├── ui/                     # local Web workspace, HTTP API, and static assets
├── agent/
│   ├── orchestration/      # main loop, tool batches, and task reporting
│   ├── routing/            # intent, modes, and execution policy
│   ├── planning/           # requirements, planning, and replanning
│   ├── validation/         # contracts, evidence, test targeting, completion policy
│   ├── editing/            # edit recovery, checkpoints, and rollback
│   ├── safety/             # permissions, safe execution, and sandboxing
│   ├── runtime/            # tool execution, processes, cancellation, Git awareness
│   ├── context/            # repository map, symbol index, and context budget
│   ├── memory/             # working and long-term memory
│   ├── progress/           # progress and stagnation control
│   └── observability/      # traces, metrics, redaction, and output control
├── tools/                  # controlled tools exposed to the model
├── evaluation/             # benchmarks, oracles, reports, and release gate
└── tests/                  # unit, integration, and behavioral tests
```

## Testing and evaluation

The latest local full regression (macOS, Python 3.13) was **745 passed**. That is a code-test result, **not the Agent's online task success rate**. CI is configured for Python 3.11, 3.12, and 3.13, builds the wheel, and checks its installed entry point outside the source checkout. Normal tests never call a paid model:

```bash
python -m pytest -q
python -m compileall -q minicodex
git diff --check
```

`MiniCodex Benchmark V1 R2` provides 30 isolated repository tasks, hidden behavioral oracles outside the agent workspace, eight smoke cases, baseline comparison, repeated runs, deterministic failure clustering, and versioned reports. Online runs require an explicit provider, model, and credentials.

```bash
python -m minicodex.evaluation.run_benchmark \
  --profile minicodex \
  --provider deepseek \
  --model deepseek-chat \
  --smoke
```

`30 tasks × 3 runs, 100% success, and zero critical errors` is the **target release gate, not a result achieved here**. This source commit has not completed that repeated online evaluation, so this README does not claim a fresh success rate. See the [Benchmark guide](docs/benchmark-v1.en.md) for metric definitions. Earlier experiments and their conditions are in the [delivery report](docs/vibecoding-refactor-report.en.md); they do not represent this commit.

## Development constraints

- `utils` does not depend on agent domain modules.
- `tools` does not depend on orchestration.
- Orchestration coordinates domain APIs instead of duplicating domain rules.
- Controllers update `TaskRuntime` through events instead of maintaining a second source of truth.
- Every core concept has one canonical import path.
- The model owns semantic judgment; permissions, budgets, safety, validation evidence, and completion remain deterministic.

Run the full test suite before submitting a focused change.

## Current limitations

- Both the CLI and Web UI are single-process sessions and cannot resume an unfinished task after a crash.
- In-progress task state and checkpoints exist only in the current process.
- Browser interaction validation requires optional Playwright and Chromium installs.
- Review mode prompts only for operations classified as `CAUTION`; Read-only separately blocks every side-effecting tool but is not kernel-level isolation.
- Service tools provide bounded processes and loopback HTTP validation, not kernel-level container isolation.
- Model, network, package registry, and operating-system conditions can still cause failures.
- Automated validation reduces risk but does not replace human code review or deployment testing.

## Documentation

| Document | 中文 | English |
| --- | --- | --- |
| Documentation index | [中文](docs/README.md) | [English](docs/README.en.md) |
| Local Web workspace | [中文](docs/ui.md) | [English](docs/ui.en.md) |
| Human-in-the-loop | [中文](docs/human-in-the-loop.md) | [English](docs/human-in-the-loop.en.md) |
| Architecture | [中文](docs/architecture.md) | [English](docs/architecture.en.md) |
| Validation Core V2 | [中文](docs/validation-core-v2.md) | [English](docs/validation-core-v2.en.md) |
| Benchmark V1 | [中文](docs/benchmark-v1.md) | [English](docs/benchmark-v1.en.md) |
| Refactoring delivery report | [中文](docs/vibecoding-refactor-report.md) | [English](docs/vibecoding-refactor-report.en.md) |
| v0.4.1 release notes | [中文](docs/releases/v0.4.1.zh-CN.md) | [English](docs/releases/v0.4.1.md) |
| v0.4.0 release notes | [中文](docs/releases/v0.4.0.zh-CN.md) | [English](docs/releases/v0.4.0.md) |
| v0.3.0 release notes | [中文](docs/releases/v0.3.0.zh-CN.md) | [English](docs/releases/v0.3.0.md) |
| v0.2.0 release notes | [中文](docs/releases/v0.2.0.zh-CN.md) | [English](docs/releases/v0.2.0.md) |
| Changelog | [中文](CHANGELOG.zh-CN.md) | [English](CHANGELOG.md) |
| MIT License | [中文参考译文](LICENSE.zh-CN.md) | [English](LICENSE) |

## License

MiniCodex is available under the [MIT License](LICENSE). A Chinese [unofficial reference translation](LICENSE.zh-CN.md) is provided for convenience; the English license text is authoritative.
