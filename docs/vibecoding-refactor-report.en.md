# Vibecoding refactoring delivery report

[简体中文](vibecoding-refactor-report.md) · **English**

| Item | Result |
| --- | --- |
| Release line | `v0.2.0` productized the CLI; `v0.3.0` adds the local Web workspace; the current Git tree is authoritative |
| Pre-change baseline | `e3510ac` |
| Latest full regression | **708 passed in 23.15s** |
| Offline VibeBench | **15/15**, false-completion rate **0** |
| Online R2 smoke | **8/8**, with zero false completion, wrong validation target, or step exhaustion |
| Compile / diff checks | `compileall` and `git diff --check` pass |

These results prove only behavior covered by local automation. They do **not** establish production reliability for every real model or repository.

---

## 1. Change overview

### Added

Major additions included:

- `agent/context/workspace_session.py`
- `agent/editing/edit_intent.py` and `work_unit.py`
- `agent/orchestration/tool_batch_result.py` and `tool_event_adapter.py`
- `agent/runtime/managed_process.py`
- `agent/validation/contracts.py`, `decision_policy.py`, `evidence.py`, `ledger.py`, `plan.py`, and `validator_resolver.py`
- `evaluation/vibebench.py`, `real_vibebench.py`, and `real_repo_bench.py`
- `tools/validation/validate_service.py` and `validate_semantic.py`
- Deterministic evidence fixtures and broad runtime/product tests

Later product work added the workspace abstraction, provider configuration, CLI diagnostics, release gate, package metadata, bilingual documentation, and a copyable demo workspace. The current Git tree is authoritative.

### Modified

The work spans architecture documentation, agent orchestration, validation, editing, safety, runtime, tools, evaluation, the CLI composition root, and their tests. Git history contains the complete diff.

### Removed

- `tests/test_complete_plan_step.py`
- `tools/planning/complete_plan_step.py`
- The obsolete validation selector module

These were superseded manual plan-completion and duplicate-selection paths. No user project files were removed. Historical versions remain recoverable from Git; no legacy compatibility wrappers were retained.

---

## 2. Core architecture

### Validation chain

```text
Requirement → ValidationPlanner → ValidationPlan → tool execution
            → ValidationPipeline → ValidationLedger
            → RequirementEvidenceResolver → TaskCompletionPolicy
```

- The pipeline normalizes results, failure identity, and baseline comparison.
- `validation/decision_policy.py` chooses the next validation action.
- A successful tool, successful edit, or single passing test does not equal task completion.

### ValidationPlan and ValidationLedger

- `validation/plan.py` defines immutable checks with IDs, requirement IDs, purpose, target, capability, required flag, strength, revision, milestone, and reason.
- `validation/ledger.py` is the only validation-history store. Green booleans are derived, never independently mutated.
- Every recorded physical edit advances the revision and invalidates old proof by default.
- Contradictory outcomes for the same validation key and revision become unstable evidence and trigger bounded consistency reruns instead of immediate repair or rollback.
- Baselines retain failure identity; regression decisions never compare only failure counts.

### Requirement-to-evidence binding

- Multi-requirement tasks bind evidence through explicit validation check IDs such as V1 and V2.
- Binding may be omitted only when exactly one candidate check exists.
- A pass for R1 cannot satisfy R2, and editing a file does not directly satisfy a file or documentation requirement.
- Once a check receives sufficiently strong deterministic evidence, its target is locked and cannot silently move after failure.
- HTTP method/path, request body, status, and content assertions all participate in target identity.
- Completion requires current proof for every required check.

---

## 3. Editing and work units

### WorkUnit

`editing/work_unit.py` groups related changes for explicit multi-path targets into a lightweight work unit.

- Each edit still advances revision independently.
- Python syntax checks can wait through an intermediate multi-file state.
- At most eight edits are allowed before validation becomes mandatory.
- Only checks with `milestone == "work_unit"` bind to the edit boundary; task-level runtime and regression checks do not block it accidentally.
- Single-file tasks avoid extra transaction machinery.

### EditIntent and post-edit verification

`editing/edit_intent.py` separates expected path, text, removed text, symbol, and explicitly allowed scope from patch/write mechanics. After a physical edit succeeds, the checkpoint executor verifies intent and adds unresolved issues to completion blockers.

`DiffQualityGate` checks:

- Scope mismatches, protected directories, large deletions, and oversized rewrites
- Duplicate imports/definitions, removed assertions, and skipped tests
- Python symbols through AST inspection

Changing a test contract requires original user authorization. A test edited by the task cannot automatically become its only sufficient proof. Exit code zero alone does not prove behavior: `echo tests passed`, constant-true assertions, removed assertions, and ordinary curl requests cannot satisfy behavioral evidence strength.

---

## 4. Context, navigation, and capabilities

### Project profile and conventions

`context/workspace_session.py` detects:

- Python, JavaScript, TypeScript, and HTML
- `pyproject.toml` and `package.json`
- pip, uv, npm, pnpm, and yarn
- Representative frameworks and test tools
- Manifest commands for test, lint, typecheck, build, start, and dev

Conventions come only from observed source patterns—async functions, return annotations, snake_case, pytest fixtures, module loggers, and exception handling. Unobserved style is never presented as a project rule.

### Change impact and navigation

The bounded change-impact resolver combines targets, imports, dependents, related tests, and nearby files for the `ContextBuilder` LOCATE → EXPAND → READ path.

- Python supports absolute/relative imports and `src`/`lib` layouts.
- JavaScript supports common relative imports.
- `TestIndex` supports nested test directories.
- `RepoMap`, `SymbolIndex`, and `TestIndex` use revision-aware caching instead of rebuilding every STANDARD turn.

### Tool capabilities

`tools/registry.py` exposes capabilities and execution metadata, including retry safety and idempotence. Tool exposure, action classification, checkpoints, edit/validation events, and safety assessment prefer capabilities over hardcoded names. MCP and multi-agent execution were not introduced.

### ToolBatchRunner split

`ToolBatchRunner` keeps ordered batch execution small, `tool_event_adapter.py` maps tool facts into requirement/plan/memory/validation/recovery events, and `tool_batch_result.py` defines the result. The message-protocol closer emits one response for every declared tool call ID before recovery or restart.

---

## 5. Runtime, services, and sessions

### TaskRuntime and event state

- `TaskState` is an immutable snapshot; production changes flow through `RuntimeEvent` and the reducer.
- Direct mutation and parallel mutable snapshots were removed.
- Work units, edit issues, external workspace changes, cancellation, and rollback synchronize through events.
- Architecture tests scan for TaskState writes that bypass the reducer and validate key domain imports in a separate interpreter.

### Evidence ladder

`EvidenceStrength` plus validation purpose and scope represent progressively stronger proof: structure → lint/typecheck → targeted tests → related regression → build → runtime → full regression.

- The planner turns observed lint/build commands into required checks when appropriate.
- Interactive HTML/game requirements need browser-runtime evidence.
- `RegressionPolicy` is risk- and scope-aware: FAST auth changes still need related regression, while README-only changes do not force unrelated full suites.

### Managed processes and service validation

`runtime/managed_process.py` reuses sandbox environment, limits, and temporary directories. Its lifecycle is: start an isolated process group → poll readiness → assert HTTP behavior → stop and clean up.

- Total deadline, cancellation propagation, 32 KB logs, and 64 KB response limits
- Rejection of occupied ports and cleanup of surviving child processes
- Loopback HTTP validation with JSON bodies, expected status, and content assertions

### WorkspaceSession and follow-up tasks

`MiniCodexAgent` reuses the workspace profile, conventions, indexes, and relevant files. Each `run` creates fresh requirements, plan, ledger, and recovery state. A follow-up never reuses green evidence or blockers from the previous task.

File fingerprints are checked before tool calls and context creation. External changes invalidate current evidence. If files change during validation, the result is inconclusive and must be rerun on the new revision.

### Safe undo and intervention

- `agent.undo_task()` reverses the latest task through existing checkpoints.
- It never runs `git reset` or automatically overwrites concurrent content.
- Safety distinguishes AUTONOMOUS, APPROVAL, and CLARIFICATION and exposes a host hook.
- The hook cannot silently override a hard safety rejection; it is an integration seam, not a built-in approval UI.

---

## 6. Evaluation and real-model feedback

### VibeBench and RealRepoBench

- `evaluation/vibebench.py`: deterministic 15-scenario HarnessBench with no paid API calls by default
- `real_vibebench.py`: provider-neutral entry point requiring an explicit `model_factory`; CI never invokes it
- `RealRepoBench`: Python, FastAPI, HTML, and TypeScript local fixtures with oracles outside the agent workspace

### Online result sequence

An early 30-case online run scored 26/30. Three failures came from overly narrow oracles that treated legal TypeScript as JavaScript data URLs, lacked `querySelector` in the DOM stub, or accepted only `addEventListener` and rejected `onclick`. R2 corrected these and added regression cases.

The remaining real false completion was `fix_python_sort_key`: a weak pre-edit acceptance happened to pass and the system ignored `no_edit_if_already_satisfied=false`. The completion gate now enforces this policy. Permission for a no-edit outcome is derived deterministically from the user's wording, never relaxed by a control model. Requirement paths also align to explicit targets and existing `src`/`lib` layouts.

The repaired R2 online smoke run (DeepSeek `deepseek-chat`, temperature 0, one run) passed 8/8. `fix_python_sort_key` became a correct one-patch task. `create_calculator_service` fell from six edits to two edits inside `src/calculator/`. The run averaged 3.5 LLM calls, 7,207.6 tokens, and 6.97 seconds per case.

A full 30-case R2 run at `b54a61c` scored 26/30 (86.67%) with zero false completion and unauthorized edits. All four failed hidden oracles actually passed, while the internal completion gate stopped safely. Three Flask cases hit subprocess `Flask.test_client()` SIGSEGV failures; one discount case received contradictory contracts. Later changes moved Flask checks to controlled loopback-service probes, tightened boundary-exception consistency, checked every edited path against allowed scope, made JSON fragments structural, and anchored Python contracts to real imports.

A six-case retest at `b3d9978` scored 2/6. It confirmed the discount and Node test-script fixes, then exposed internal `purpose` metadata leaking into `ValidateServiceTool` and mixed real/hallucinated Python paths. The execution boundary now filters Harness metadata against backend schemas and removes hallucinated import paths. Workspace profiles now refresh before post-edit regression discovery.

The second six-case retest at `0ec76cf` improved to 4/6. Flask and discount cases passed; the Node case dropped from 17 steps/88,898 tokens to 2 steps/6,189 tokens. Remaining failures came from invented Express/calculator paths. Planner paths were downgraded to suggestions that can reference only existing files, while explicit user paths and typed file contracts still authorize creation.

A focused third retest at `167ef58` passed 2/2 with zero hidden-oracle failure, wrong-file edit, unauthorized edit, or step exhaustion. One calculator run still used two self-selected acceptance commands after a package-export failure, producing a wrong-validation-target signal. The execution boundary therefore added exact target binding: when a resolved validator exists, acceptance/regression calls must match it exactly; arbitrary commands remain available only as diagnostics.

At `ae2d98e`, a one-case online confirmation passed the calculator hidden oracle with zero wrong target, wrong file, unauthorized edit, failed tool call, or ghost step. Steps fell from seven to four and tokens from 24,286 to 12,927. A later six-case gate scored 5/6 with zero wrong target. The only failure, `modify_discount_bounds`, received mutually exclusive requirements for the same out-of-range percentage—return zero and raise `ValueError`—and safely exhausted its budget without false completion. This proves exact target binding works and identifies upstream contract-consistency validation as remaining work.

### Action-efficiency metrics

Metrics include time to first edit, inspections/searches before edit, tool/model calls, tokens, repeated reads/searches, wrong file/target, validation-to-edit ratio, stagnation, exhaustion, rollback, recovery, and optional dollar cost.

The deterministic offline suite passes 15/15 with zero false completion. Scripted token counts are synthetic and are not presented as provider measurements.

---

## 7. Productization and workspace reliability

- `WorkspaceConfig` separates application root, target workspace, runtime/sandbox/trace roots, and stable repository key.
- `minicodex` defaults to the current directory; `--workspace PATH` selects any existing directory.
- File, edit, command, test, Web, Git, index, and checkpoint tools share the selected workspace.
- Required checks survive missing capabilities; resolver states are resolved, capability-missing, or target-unresolved.
- Validation contracts use a typed union for file, test, command, HTTP, browser, and semantic proof.
- Browser contracts require selector, action, and post-action assertion.
- Semantic validation attempts deterministic literal proof before an optional bounded JSON judge.
- Runtime data lives under `~/.minicodex/workspaces/`; `.minicodex` remains ignored/protected if encountered in a target repository.
- The target project's `.venv`/`venv` is preferred, with `uv.lock` and `poetry.lock` awareness.
- The validation loop prepares the current required check before rendering a prompt; `TARGET_UNRESOLVED` permits only one bounded reconnaissance action.
- Product CLI commands, offline/JSON diagnostics, provider-neutral environment names, wheel packaging, and Python 3.11–3.13 CI shipped in `v0.2.0`.

---

## 8. Verification history

### Commands executed

Commands used throughout the work:

```sh
python -m pytest -q
python -m compileall -q minicodex
git diff --check
python -m minicodex.evaluation.vibebench
```

The CI path runs deterministic pytest/compile/package checks and never calls a paid provider.

### Result progression

| Milestone | pytest | Notes |
| --- | --- | --- |
| First refactor | 555 passed | VibeBench 15/15 |
| Reliability closeout | 559 passed | Resolver, RealVibeBench, CI |
| Workspace productization | 566 passed | Workspace, typed contracts, semantic validation |
| External hidden oracles | 572 passed | Rebinding and parameter validation |
| Product gate and R2 | 654 passed | Offline VibeBench 15/15 |
| Dogfood and full-R2 repairs | 662 passed | Flask loopback validation |
| Success-quality tightening | 665 passed | Per-path scope, structural JSON, import anchors |
| Tool-schema path constraints | 666 passed | Generated read/edit schemas constrained to contract scope |
| Targeted R2 feedback fixes | 668 passed | Metadata isolation and hallucinated-path cleanup |
| Regression-discovery ordering | 669 passed | Refresh workspace profile before creating regression checks |
| Edit-scope provenance | 672 passed | Planner cannot authorize nonexistent paths |
| Exact validation target gate | 673 passed | Blocks substitute acceptance/regression commands |
| v0.2.0 product release | **682 passed** | run/chat/doctor, diagnostics, wheel, 3-version CI, install smoke |
| Minimum viable Web UI | **689 passed** | File tree, code/diff, Agent chat, task state, Trace terminal, and checkpoint Accept/Reject |
| Human-in-the-loop phase one | **700 passed** | `CAUTION` pause, allow once/task, deny, cancellation and timeout, redacted preview, bilingual UI |
| Human-in-the-loop phase two | **708 passed** | Review/Auto/Read-only modes, Trace approval audit, per-file diff navigation, layered read-only enforcement |

---

## 9. Remaining boundaries

- One full 30-case real-model experiment, targeted gates, and focused confirmation runs have been performed; the formal 30 cases × 3 repetitions are deferred by the release plan.
- Requirement extraction can still create mutually exclusive validation contracts. More steps cannot solve that contradiction; pre-activation consistency checks remain future work.
- Human-in-the-loop passed real local-browser interaction checks, but browser validation is still outside the required CI path.
- Requirement extraction and target selection still combine model judgment with bounded heuristics. Deterministic binding cannot prove arbitrary documentation semantics.
- Navigation is bounded: workspace scans, convention/dependency sampling, and test indexing have explicit file limits.
- External-change detection uses stat fingerprints, not filesystem transactions or locks; whole-task undo covers only checkpointed agent edits.
- Service isolation inherits the process sandbox and loopback HTTP boundary; it is not kernel-level filesystem/network isolation.
- Work units are derived from explicit targets and are not perfect semantic grouping for arbitrary natural language.
- Hundreds of tests and scripted scenarios cannot establish universal production reliability.

---

## 10. Related documentation

- [Architecture](architecture.en.md)
- [Validation Core V2](validation-core-v2.en.md)
- [Benchmark V1](benchmark-v1.en.md)
- [English README](../README.en.md)
