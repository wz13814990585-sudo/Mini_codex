# MiniCodex vibecoding architecture

MiniCodex follows one control-plane boundary: semantic understanding and
strategy belong to bounded LLM calls; factual state, safety, execution, policy,
recovery, and completion belong to the deterministic Harness.

At task start `TaskRouter` makes one stateless control-model call returning a
strict `RoutingDecision`: `TaskIntent`, `ExecutionMode`, independent
`needs_plan`, confidence, and a bounded debug reason. Only the raw current task
is sent. The response is schema-validated; malformed/provider/timeout failures
use one conservative deterministic fallback. Path extraction remains structural
and workspace-normalized. The old keyword complexity scorer and intent
classifier are not production routing paths.

`ExecutionPolicy` translates the semantic mode into fixed step, retry, tool,
validation, recovery, and context limits. The model cannot choose resources.
Runtime scope may escalate monotonically FAST → STANDARD → COMPLEX without
resetting consumed budget. Direct execution may activate a plan once when new
facts prove coordination is necessary; replan attempts remain separately
bounded.

Inspect-only requests cannot see edit or dependency-install capabilities.
Informational requests normally see no tools. Model prose cannot complete a
modify task: the task must edit and validate, or validate that the requested
state already exists.

## State, progress, and phases

`TaskState` is the compact orchestration read-model. It projects intent, mode,
planning state, requirement IDs, request targets, relevant paths,
edit/validation/rollback/plan revisions, completed steps, validation flags,
pressure counters, budget, and outcome.
Filesystem contents, tool results, validation evidence, and plan objects remain
the sources of truth.

`AgentPhase` has seven states: `INSPECTING`, `ACTING`, `VALIDATING`, `FIXING`,
`FINALIZING`, `DONE`, and `BLOCKED`. `ActionController` consumes a mandatory
`ProgressSignal`; it does not infer progress from arbitrary state changes.
Reads are observations, edits and completed plan criteria advance, unchanged
validation does not advance, an improved failure count advances, a passed-to-
failed transition regresses, and rollback is not positive advancement.
`ValidationFingerprint` compares only the same stable
purpose/scope/normalized-target/validator series and includes failure identities,
not only counts. Contradictory same-revision results become unstable evidence.

## Runtime responsibilities

The shared flow is:

1. Project current `TaskState` and build one provider turn.
2. `TurnBuilder` delegates system text to `PromptBuilder`, phase-specific task
   context to `ContextBuilder`, and schemas to `ToolSchemaProvider`.
3. `ToolCallRunner` owns prepare → restrict → duplicate-check → safe execution
   for one call.
4. `ToolBatchRunner` owns the complete ordered provider batch and emits exactly
   one tool result for every declared call, including skipped calls before a
   control transition.
5. `PlanOrchestrator` owns step attempt, local recovery, and replan transitions.
6. `ValidationPipeline` normalizes tool output into current-revision facts,
   baseline deltas, stable keys, failure identities, and instability;
   `ProgressController` describes only comparable trends.
7. A compact stateless `SemanticRegressionJudge` runs only for a genuinely
   ambiguous cross-revision regression. Its recommendation cannot edit,
   rollback, bypass safety, or complete the task.
8. Deterministic recovery permits bounded materially different repair before
   `RollbackCoordinator` may restore a conflict-free checkpoint.
9. `CompletionHandler` is the only termination owner. `TaskReportBuilder`
   renders the final coding report immediately, without another model call.

Normal product flows:

- `MODIFY + FAST`: minimal inspect → edit → proportional acceptance → done.
- `MODIFY + STANDARD`: optional short plan → edit → acceptance → relevant regression → done.
- `MODIFY + COMPLEX`: optional plan → iterative edit → acceptance → full regression → done.
- `INSPECT_ONLY`: inspect → report, with zero edits.
- `INFORMATIONAL`: answer directly.

## Editing, recovery, and safety

`EditStrategyHint` recommends `write_file` for new files, `patch_file` for
small exact edits, `replace_symbol` for known Python symbols, and
`replace_lines` for known line regions. It is advisory and never auto-edits.
`EditRetryPolicy` recovers locally first: stale/range/ambiguous edits reread the
target, missing symbols use one symbol search, test failures focus on the
failing test or traceback path, and dependency failures inspect the manifest.

All mutations still pass through `SafetyToolExecutor`, raw no-edit permission
guards, workspace/protected-path rules, anti-test-gaming checks, and checkpoint
capture/seal. Checkpoint execution detects concurrent changes, and rollback
refuses to overwrite a post-checkpoint external edit. Rollback creates a new
monotonic revision, invalidates validation/plan evidence and repository caches,
and resynchronizes task-local memory. A higher failed count alone never rolls
back. Stable `EditFailureType` and `ReasonCode` values drive control logic;
user-facing text does not.

## Validation targeting

`ValidationSelector` recommends one proportional validator. Static HTML uses
`validate_static_web`, which proves structure, inline syntax, and configured
static requirements—not click, keyboard, gameplay, or runtime state. The
optional `validate_browser_app` tool uses Playwright for page load, console
errors, selectors, text, click, keypress, and basic DOM/text changes. It is
registered only when Playwright is available; static validation remains the
fallback.

A revision-cached, AST-based `TestIndex` maps imported/referenced Python source
modules to tests. `TestTargetResolver` ranks exact basename, import match,
same-package test, then broader test directory. Only genuinely focused
candidates are labelled acceptance; package/broad candidates remain
regression. A source module is never used as a pytest acceptance target.
`run_tests` emits conservative repo-relative `failure_paths` from failed node
IDs and traceback/error locations, plus bounded failure fingerprints. Regression
baseline evidence distinguishes pre-existing, persisting, resolved, and newly
introduced failures. Tool execution failure and timeout are inconclusive
environment evidence, not automatic code failure.

`RelevantPathResolver` derives scope from request targets, edited paths, failed
tests, tracebacks, validation targets, stale edits, plan criteria, symbol-search
recovery, and explicit dependency-resolution evidence. It does not add every
manifest to unrelated tasks.

## Context, memory, capabilities, and UX

`ContextBuilder` changes content by phase: inspecting sees targets/repository
fragment; acting sees the edit hint and exact current state; validating sees
changed targets and the recommended validator; fixing sees the latest failure
paths; finalizing sees only missing evidence. Older tool payloads become short
facts. Exact code is re-read from the workspace when needed.

`TaskRequirements` stores independently provable user outcomes and their current
evidence. Multi-goal/coordinated tasks may use one stateless requirements call;
obvious FAST tasks avoid it. Green validation cannot finish a task while an
explicit requested outcome remains unproven.

Working-memory entries carry path and revision. Editing a path removes older
observations for that path before recording the new revision. Memory is a cache;
the workspace remains authoritative.

Task control state and checkpoints are task-local and in memory. MiniCodex does
not claim resumable in-flight tasks after a process crash. A restarted process
must inspect the physical workspace and establish fresh validation; it cannot
reuse pre-crash validation or rollback state.

`ToolRegistry` supports lightweight capabilities such as `filesystem.read`,
`filesystem.write`, `code.search`, `code.edit`, `process.run`, `test.run`,
`validation.static_web`, `validation.browser`, `dependency.install`, and
`git.inspect`, with deterministic name-based defaults for built-in tools.

CLI levels are `normal`, `verbose`, and `debug`. Normal hides Harness/provider
noise and internal enums. Verbose retains execution/phase diagnostics. Debug
also exposes outcome tokens and the post-task trace summary. Normal final
reports contain changed files and validation results only.

## Package ownership

- `agent/`: only the `MiniCodexAgent` facade, central `TaskState`, shared reason
  codes, and package exports.
- `agent/context/`: context budget and compaction plus repository-map and symbol
  context used during navigation.
- `agent/orchestration/`: loop control, provider turns, tool batches, planning and
  validation coordination, completion handling, and task reports.
- `agent/routing/`: semantic routing schema/prompt/fallback, task intent,
  execution mode, and deterministic execution policy.
- `agent/progress/`: progress signals, action pressure, and finalization control.
- `agent/planning/`: task requirements, plans, planning/replanning, plan quality,
  and step evidence.
- `agent/validation/`: evidence normalization, validation selection, test indexing
  and targeting, relevant paths, regression policy, and completion policy.
- `agent/editing/`: edit strategy/retry, checkpoints, verified execution, rollback,
  and rollback coordination.
- `agent/dependency/`: manifest-aware dependency resolution policy.
- `agent/memory/`: task-local working memory and persistent memory integration.
- `agent/safety/`: permission policy, fail-closed execution, and process sandboxing.
- `agent/runtime/`: tool execution, cancellation, asynchronous task mechanics,
  and Git working-tree awareness.
- `agent/observability/`: execution/token metrics, structured trace events and
  adapters, and output-level selection.
- `tools/`: model-callable capabilities grouped into `filesystem`, `search`,
  `editing`, `execution`, `validation`, `planning`, and read-only `git`; only
  tool-system core types stay shallow in `base.py`, `registry.py`, and
  `results.py`.
- `utils/`: domain-neutral helpers only, including workspace path resolution.

## Dependency rules and canonical imports

Dependency direction is deliberate: `utils` does not depend on agent domains;
tools do not depend on orchestration; domain packages avoid importing the
`MiniCodexAgent` facade; orchestration coordinates domain APIs; and `agent.py`
acts as the composition root. Package `__init__.py` files expose intentional
stable APIs. A few imports are lazy solely to prevent package-initialization
cycles while preserving the identity of the canonical class or enum. Every
concept has one canonical module path; the source tree contains no legacy
module wrappers or compatibility import paths.

`ExecutionMetrics` and the deterministic evaluation harness separate main-agent,
routing, requirements, and semantic-judge calls/tokens/latency. They also record
mode escalation, late planning, repair, validation/flaky reruns, prevented
premature rollback, outcome, false completion, wrong edits, tool counts,
replans, rollbacks, action pressure, and budget exhaustion. Prompt versions and
configured model names are observable. The evaluation package contains both a
30-task end-to-end catalog and a balanced English/Chinese/mixed routing corpus.
