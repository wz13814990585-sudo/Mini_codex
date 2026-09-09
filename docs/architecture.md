# MiniCodex vibecoding architecture

The package migration is structural: it changes ownership and import paths but
intentionally introduces no execution, policy, validation, safety, or output
behavior changes.

MiniCodex uses one shared coding loop. `TaskRouter` composes two orthogonal,
deterministic decisions: `IntentClassifier` selects `TaskIntent` (`MODIFY`,
`INSPECT_ONLY`, or `INFORMATIONAL`), while `ComplexityRouter` selects
`ExecutionMode` (`FAST`, `STANDARD`, or `COMPLEX`). Intent controls
authorization and final-response semantics. Mode controls planning depth,
budgets, context, recovery, and proportional regression requirements.

Inspect-only requests cannot see edit or dependency-install capabilities.
Informational requests normally see no tools. Model prose cannot complete a
modify task: the task must edit and validate, or validate that the requested
state already exists.

## State, progress, and phases

`TaskState` is the compact orchestration read-model. It projects intent, mode,
phase, request targets, relevant paths, edit/validation/rollback/plan revisions,
completed steps, validation flags, pressure counters, budget, and outcome.
Filesystem contents, tool results, validation evidence, and plan objects remain
the sources of truth.

`AgentPhase` has seven states: `INSPECTING`, `ACTING`, `VALIDATING`, `FIXING`,
`FINALIZING`, `DONE`, and `BLOCKED`. `ActionController` consumes a mandatory
`ProgressSignal`; it does not infer progress from arbitrary state changes.
Reads are observations, edits and completed plan criteria advance, unchanged
validation does not advance, an improved failure count advances, a passed-to-
failed transition regresses, and rollback is not positive advancement.
`ValidationFingerprint` compares only the same purpose/scope/path series.

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
6. `ValidationPipeline` normalizes tool output into evidence;
   `ValidationOrchestrator` owns trend and next-action policy;
   `RollbackCoordinator` owns safe checkpoint restoration.
7. `CompletionHandler` is the only termination owner. `TaskReportBuilder`
   renders the final coding report immediately, without another model call.

Normal product flows:

- `MODIFY + FAST`: minimal inspect → edit → targeted validation → done.
- `MODIFY + STANDARD`: short plan → edit → acceptance → relevant regression → done.
- `MODIFY + COMPLEX`: plan → iterative edit → acceptance → full regression → done.
- `INSPECT_ONLY`: inspect → report, with zero edits.
- `INFORMATIONAL`: answer directly.

## Editing, recovery, and safety

`EditStrategyHint` recommends `write_file` for new files, `patch_file` for
small exact edits, `replace_symbol` for known Python symbols, and
`replace_lines` for known line regions. It is advisory and never auto-edits.
`EditRetryPolicy` recovers locally first: stale/range/ambiguous edits reread the
target, missing symbols use one symbol search, test failures focus on the
failing test or traceback path, and dependency failures inspect the manifest.

All mutations still pass through `SafetyToolExecutor`, workspace guards, and
checkpoint capture/seal. Cross-revision regression may restore the responsible
checkpoint. Rollback creates a new monotonic edit revision and invalidates old
validation evidence. Stable `EditFailureType` and `ReasonCode` values drive
control logic; user-facing text does not.

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
IDs and traceback/error locations.

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

Working-memory entries carry path and revision. Editing a path removes older
observations for that path before recording the new revision. Memory is a cache;
the workspace remains authoritative.

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
- `agent/routing/`: task intent, complexity, execution mode, and execution policy.
- `agent/progress/`: progress signals, action pressure, and finalization control.
- `agent/planning/`: plans, planning/replanning, plan quality, and step evidence.
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

`ExecutionMetrics` and the deterministic evaluation harness record intent,
mode, success/outcome, false completion, wrong edit, LLM/tool/inspection/edit/
validation counts, first-edit latency, replans, rollbacks, action pressure,
prompt tokens, and budget exhaustion. The fixed real-task catalog contains 30
CREATE, MODIFY, FIX, INSPECT, and INFORMATIONAL cases.
