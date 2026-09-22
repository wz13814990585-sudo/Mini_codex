# MiniCodex vibecoding architecture

[简体中文](architecture.md) · **English**

MiniCodex follows one control-plane boundary: **semantic understanding and strategic judgment belong to bounded LLM calls; factual state, safety, execution, policy, recovery, and completion belong to the deterministic Harness.**

See the [refactoring delivery report](vibecoding-refactor-report.en.md) for the requirement-to-evidence redesign and validation history. A reusable `WorkspaceSession` stores bounded project knowledge. Every request receives fresh task-local runtime, requirements, validation ledger, recovery, and plan state.

At task start, `TaskRouter` makes one stateless control-model call and returns a strict `RoutingDecision`: `TaskIntent`, `ExecutionMode`, an independent `needs_plan` flag, confidence, and a bounded diagnostic reason. It receives only the current raw request. Responses are schema-validated; malformed, provider, or timeout failures use the same conservative deterministic fallback. Path extraction stays structured and workspace-normalized. The old keyword complexity scorer and intent classifier are **not** on the production routing path.

`ExecutionPolicy` maps the semantic mode to fixed step, retry, tool, validation, recovery, and context limits. The model cannot choose its own resources. Runtime scope can increase monotonically from FAST → STANDARD → COMPLEX without resetting consumed budget. Direct execution can activate one plan when new facts prove coordination is needed; replanning has a separate limit.

Read-only inspection requests never see edit or dependency-install tools. Informational requests normally see no tools. Model prose cannot complete a modification task: the task must produce and validate an edit, or prove that the requested state already exists when the user authorized a no-edit outcome.

## State, events, progress, and phases

`TaskRuntime` owns an immutable authoritative `TaskState` snapshot for one run. Filesystem content and normalized tool results are factual inputs. Controllers are caches or focused services, not competing orchestration states. Important changes become explicit `RuntimeEvent` objects consumed by the pure `reduce_task_state` function:

```text
Workspace / tool facts → RuntimeEvent → reducer → current TaskState
                                                   ↓
                                            ContextBuilder
                                                   ↓
                                               model action
```

State includes run ID, intent, mode, phase, budget, targets, requirements, edit/validation/rollback/plan revisions, current evidence, progress pressure, recovery level, blockers, and outcome. State transitions can be tested independently. `task_progress_state()` returns this state directly instead of reconstructing another truth from controller polling.

`AgentPhase` has seven values: `INSPECTING`, `ACTING`, `VALIDATING`, `FIXING`, `FINALIZING`, `DONE`, and `BLOCKED`. `ActionController` consumes explicit `ProgressSignal` values and does not infer progress from arbitrary state changes. Reads are observations; edits and completed plan criteria advance progress; unchanged validation does not; fewer failures do; pass-to-fail transitions are regressions; rollback alone is not positive progress. `ValidationFingerprint` compares a stable purpose/scope/normalized-target/validator sequence and includes failure identity, not just failure count. Contradictory results in one revision become unstable evidence.

## Runtime responsibilities

The shared flow is:

1. `TaskBootstrapper` applies routing and policy, resets task-local services, builds requirements and validation contracts, starts `TaskRuntime`, gathers repository context, and optionally creates the initial plan.
2. Completion eligibility is evaluated from current state and evidence.
3. Bounded mode, plan, phase, and budget policies are applied.
4. `TurnBuilder` selects the system prompt, builds phase context, decorates tool schemas, and filters availability through `ExecutableToolPolicy`.
5. `ToolCallRunner` handles preparation → restriction → revision-aware duplicate detection → safe execution for one call.
6. `ToolBatchRunner` executes a complete ordered provider batch and emits exactly one result for every declared tool call, including calls skipped before a control transition.
7. `PlanOrchestrator` owns step attempts, local recovery, and replanning transitions.
8. `ValidationPlanner` creates independent requirement checks. `ValidationPipeline` normalizes execution facts. `ValidationLedger` stores revisioned history, target bindings, baselines, and instability. `RequirementEvidenceResolver` derives satisfaction from sufficient current proof. `ValidationDecisionPolicy` chooses the next validation action; `ProgressController` only describes comparable trends.
9. A compact stateless `SemanticRegressionJudge` runs only for genuinely ambiguous cross-revision regressions. It cannot edit, rollback, bypass safety, or complete a task.
10. Deterministic recovery allows bounded, materially different repairs; only then may `RollbackCoordinator` restore a conflict-free checkpoint.
11. `CompletionHandler` is the only termination owner. `TaskReportBuilder` renders the final report without another model call.

Common product paths:

- `MODIFY + FAST`: minimal inspection → edit → proportional acceptance → completion
- `MODIFY + STANDARD`: optional short plan → edit → acceptance → related regression → completion
- `MODIFY + COMPLEX`: optional plan → iterative edits → acceptance → full regression → completion
- `INSPECT_ONLY`: inspect → report, with zero edits
- `INFORMATIONAL`: direct answer

Plans contain outcome descriptions, expected targets, dependencies, acceptance criteria, status, and evidence. Evidence reconciles criteria automatically. The manual plan-completion tool was removed. When explicit requirements and proportional current-revision validation are satisfied, bookkeeping-only plan residue is superseded and cannot keep the agent alive.

## Editing, recovery, and safety

`EditStrategyHint` recommends `write_file` for new files, `patch_file` for precise local changes, `replace_symbol` for known Python symbols, and `replace_lines` for known ranges. It never edits automatically. `EditRetryPolicy` first performs local recovery: stale/range/ambiguity failures reread the target; missing symbols trigger one symbol search; failed tests focus on the failing test or traceback path; dependency failures inspect manifests.

Every change still passes through `SafetyToolExecutor`, the no-edit guard, workspace and protected-path rules, anti-test-cheating checks, and checkpoint capture/sealing. Checkpoint execution detects concurrent changes; rollback refuses to overwrite content changed after the checkpoint. Rollback creates a new monotonic revision, invalidating validation/plan evidence and resynchronizing task-local memory. A higher failure count alone does not trigger rollback. Stable `EditFailureType` and `ReasonCode` values drive control logic; user-facing text does not.

## Validation target selection

`ValidationPlanner` creates a proportional validation contract for each requirement, and `ValidatorResolver` binds it to a concrete validator from registered capabilities. Static HTML uses `validate_static_web` to prove structure, inline syntax, and static requirements—not clicks, keyboard input, gameplay, or runtime state. Optional `validate_browser_app` uses Playwright for page load, console errors, selectors, text, clicks, keypresses, and basic DOM/text changes. It is registered only when Playwright is available; static validation remains a fallback, never a substitute for required interaction proof.

A revision-cached AST-based `TestIndex` maps imported or referenced Python source modules to tests. `TestTargetResolver` ranks exact basenames, import matches, same-package tests, and broader test directories. Only focused candidates count as acceptance; package-level or broad suites remain regression. Source modules are never used as pytest targets. `run_tests` emits conservative workspace-relative `failure_paths` from failed node IDs and traceback/error locations, plus a bounded failure fingerprint. Regression baseline evidence distinguishes pre-existing, persistent, resolved, and newly introduced failures. Tool execution failures and timeouts are uncertain environment evidence, not automatic code failures.

`RelevantPathResolver` derives scope from request targets, edited paths, failed tests, tracebacks, validation targets, stale edits, plan criteria, symbol-search recovery, and explicit dependency evidence. It does not inject every manifest into unrelated tasks.

## Context, memory, capabilities, and experience

`ContextBuilder` is the only context path. Content changes by phase: inspection sees targets and repository excerpts; action sees editing guidance and exact current state; validation sees changed targets and the recommended validator; fixing sees the latest failure paths; finalization sees only missing evidence. Older tool payloads are compacted into short facts. Exact code is reread from the workspace when needed.

`TaskRequirements` stores independently provable user outcomes and their current evidence. Multi-goal or coordinated tasks may use one stateless requirements call; obvious FAST tasks may skip it. Green validation cannot finish the task while an explicit requested result remains unproved.

No-edit completion is a deterministic permission derived from the user's wording, not a control-model preference. Only requests that explicitly allow “do not change it if already satisfied” can produce `ALREADY_SATISFIED`. Ordinary create/fix/change/update/refactor requests must still edit even if a weak pre-edit check happens to pass. Requirement-model paths are aligned to explicit targets and existing `src/`/`lib/` layouts so package import names do not create duplicate top-level source trees.

Working-memory entries carry paths and revisions. Editing a path first removes stale observations for that path, then records the new revision. Memory is a cache; the workspace is authoritative.

Task control state and checkpoints are task-local and in-process. MiniCodex does not claim crash recovery for unfinished work. A restarted process must inspect the physical workspace and establish fresh validation; it cannot reuse old evidence or rollback state.

`ToolRegistry` exposes backend-neutral `ToolMetadata`: capabilities, risk, side-effect class, read-only status, timeout class, and backend. Lightweight capabilities include `filesystem.read`, `filesystem.write`, `code.search`, `code.edit`, `process.run`, `test.run`, `validation.static_web`, `validation.browser`, `dependency.install`, and `git.inspect`. This is the seam for future local or remote backends; MCP networking is not implemented.

The hot path for model turns is centralized in `orchestration/turn_builder.py`: prompt selection, context construction, Harness metadata injection, and tool availability filtering. Runtime interception and schema filtering both read `ExecutableToolPolicy`. `ActionController` retains only counters and checks that depend on concrete paths or content, preventing policy drift.

FAST tasks without a dedicated semantic judge cannot terminate through a fallback `semantic` contract. That check stays unproved so the model can supply explicitly bound test or command evidence. Strong runtime contracts such as browser or HTTP checks still block when required capabilities are missing.

CLI output levels are `normal`, `verbose`, and `debug`. `normal` hides Harness/provider noise and internal enums. `verbose` keeps execution and phase diagnostics. `debug` also exposes result tokens and post-task trace summaries. The normal final report includes only changed files and validation results.

## Local Web workspace

`minicodex ui` is a thin product shell over the existing Runtime; it does not own a second Agent orchestration path. `MiniCodexUIController` calls `build_agent()` for each task, executes it in the background through `AsyncAgentRunner`, and projects authoritative data directly:

- Task phases, mode, budget, and outcome come from `TaskState`.
- The activity terminal and counters come from `TraceRecorder`.
- Worktree status and diffs come from `GitRepositoryInspector`.
- Reject calls the current Agent's `undo_task()` and restores this task through its sealed checkpoint chain.

Accept only means that the user keeps the current physical changes; it does not fabricate commits, validation evidence, or completion. Reject detects external modifications made after a checkpoint and fails closed instead of using `git reset`. A pending change set blocks the next task until Accept or Reject, preserving the previous task's rollback boundary.

The HTTP layer binds only to a loopback address, requires a random per-session token for mutations, and validates the local Host. Responses enable CSP and disable framing and MIME guessing. File APIs use the shared workspace path boundary, cap preview size, reject binaries and symlinks, and hide `.env`, private keys, and common credential files. The frontend is native HTML, CSS, and JavaScript packaged in the wheel, so it adds neither another service framework nor a frontend build chain.

## Package ownership

| Package | Responsibility |
| --- | --- |
| `agent/` | `MiniCodexAgent` facade, central `TaskState`, shared reason codes, and package exports |
| `agent/context/` | Context budgets/compaction, repository map, symbol context, and navigation |
| `agent/orchestration/` | Loop control, provider turns, tool batches, planning/validation coordination, completion, and reporting |
| `agent/routing/` | Routing schema/prompt/fallback, intent, mode, and deterministic execution policy |
| `agent/progress/` | Progress signals, action pressure, and finalization control |
| `agent/planning/` | Requirements, plans, planning/replanning, plan quality, and step evidence |
| `agent/validation/` | Evidence normalization, validation selection, test indexing/targeting, relevant paths, regression, and completion |
| `agent/editing/` | Edit strategy/retry, checkpoints, verified execution, rollback, and rollback coordination |
| `agent/dependency/` | Manifest-aware dependency resolution |
| `agent/memory/` | Task-local working memory and persistent-memory integration |
| `agent/safety/` | Permission policy, fail-closed execution, and process sandbox |
| `agent/runtime/` | Tool execution, cancellation, async mechanisms, and Git worktree awareness |
| `agent/observability/` | Execution/token metrics, structured traces, adapters, redaction, and output levels |
| `ui/` | Local HTTP product shell, task-review session, read-only file APIs, and packaged static interface |
| `tools/` | Controlled model tools grouped by filesystem, search, editing, execution, validation, planning, and read-only Git capabilities |
| `utils/` | Domain-independent helpers such as workspace path handling |

## Dependency rules and canonical imports

Dependency direction is intentional: `utils` does not depend on agent domains; tools do not depend on orchestration; domain packages avoid importing the `MiniCodexAgent` facade; orchestration coordinates domain APIs; `agent.py` is the composition root. Package `__init__.py` files expose deliberate stable APIs. A few imports are lazy only to prevent initialization cycles while preserving canonical class and enum identities. Every concept has one canonical module path; the source tree contains no legacy compatibility wrappers.

`ExecutionMetrics` and the deterministic evaluation Harness distinguish main-agent, routing, requirements, and semantic-judge calls, tokens, and latency. They also record mode escalations, late planning, repair, validation/unstable reruns, prevented premature rollbacks, outcomes, false completion, wrong edits, tool counts, main-loop steps, replanning, rollback, action pressure, and budget exhaustion. Prompt version and configured model are observable. `minicodex-bench-v1-r2` reuses the same Harness for 30 fixed repository tasks, post-run hidden oracles, baseline/MiniCodex profiles, repeated runs, failure clustering, and versioned output. See the [Benchmark guide](benchmark-v1.en.md).
