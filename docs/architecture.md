# MiniCodex control-plane architecture

MiniCodex uses one shared agent loop for FAST, STANDARD, and COMPLEX work. The
router selects an `ExecutionPolicy`; it does not select a separate runtime.
Mode differences are limited to planning, budgets, exposed tools, context,
recovery, and proportional regression requirements.

Before execution, `TaskRouter` also classifies the final-response contract.
Informational questions may return ordinary model text. Coding/action requests
use `TASK_REPORT`: model prose is never completion evidence. An unevidenced
text response receives one execution correction and the task continues. Only
`CompletionPolicy` readiness, an explicit concrete `BLOCKED:` reason, or budget
exhaustion can terminate a coding task.

## State and phases

`TaskState` is the orchestration read-model. It projects the current mode,
phase, user request, edit/validation/rollback/plan revisions, completed steps,
validation flags, progress counters, remaining budget, and final outcome.
Filesystem contents, tool results, validation evidence, and plan objects remain
the underlying sources of truth.

The phase machine is deliberately small:

1. `INSPECTING`: at most two or three reconnaissance calls.
2. `ACTING`: perform a concrete edit or other required action.
3. `VALIDATING`: obtain artifact-appropriate evidence; unrelated search is
   rejected.
4. `FIXING`: after failed validation or stale edit context, allow one targeted
   source read and then an edit.
5. `FINALIZING`: permit only missing validation, a necessary edit, evidenced
   plan completion, or a concrete blocker.
6. `DONE` and `BLOCKED`: terminal outcomes.

`ActionController` is the only generic inspection/no-state-change pressure
source. It consumes `ProgressSignal` and monotonic task facts. Edit and plan
advancement reset pressure; validation sequence numbers, repeated reads,
searches, repository-map refreshes, rollback, and identical observations do
not. `ValidationFingerprint` compares only the same purpose/scope/path series:
fewer failures or failed-to-passed advances, unchanged results do not, and a
higher failure count regresses.

## Execution flow

The shared loop performs the following sequence:

1. Refresh the task-state projection and build mode-filtered context.
2. `TurnBuilder` prepares compact provider messages and mode-filtered schemas.
3. `ToolBatchRunner` applies parse, restriction, duplicate, safety, checkpoint,
   and execution ordering.
4. `ValidationOrchestrator` normalizes progress, recovery, rollback, and the
   next validation transition.
5. `CompletionHandler` applies the single exit policy and
   `TaskReportBuilder` renders coding-task outcomes without another LLM call.
6. Close every skipped provider tool call before restarting or finishing.

FAST is planless and immediately completes when targeted acceptance evidence
passes. STANDARD uses a short outcome plan and focused regression. COMPLEX adds
long-term memory, broader recovery, limited replanning, and full regression.

## Edit, dependency, and validation reliability

Checkpointed edit tools return structured metadata including `path`,
`checkpoint_id`, `changed`, and `edit_kind`. Exact patch, line, and symbol
guards return typed `EditFailureType` and stable `ReasonCode` values instead of
requiring downstream message matching. `EditRetryPolicy` permits bounded local
recovery: stale/ambiguous/range failures receive one targeted read and retry;
missing symbols receive one symbol search and narrower retry; no-change points
to already-satisfied evidence; permission denial is a blocker.

`DependencyResolver` reads `pyproject.toml` and `requirements*.txt` before a
Python install. Declared dependencies may be installed. Undeclared project
dependencies require a manifest edit first. Isolated examples avoid unrelated
manifest mutation.

`ValidationSelector` recommends one proportional validator from artifact type.
Static HTML uses `validate_static_web`. `TestTargetResolver` maps a Python
source to an existing focused test; a source module is never sent to pytest as
acceptance evidence. `run_tests` exports conservative repo-local
`failure_paths`, and `RelevantPathSet` combines request targets, edits,
tracebacks, failed tests, plan criteria, stale targets, and dependency config
to permit focused FIXING reads while blocking unrelated reconnaissance. Other
artifacts can use a labelled acceptance command. A future
`validate_browser_app` tool can register as a runtime browser extension without
changing the loop or validation state model.

## Safety and observability

All edits still flow through safety checks and checkpoint capture/seal.
Cross-revision validation regression can restore the responsible checkpoint;
rollback creates a new monotonic edit revision and invalidates old evidence.
Provider tool-message ordering and async cancellation boundaries are preserved.

`ExecutionMetrics` records mode, LLM/tool/inspection/edit/validation calls,
calls before first edit and validation, action pressure, replans, rollbacks,
budget exhaustion, prompt tokens, and final outcome/reason. The deterministic
evaluation harness exports those fields with each case result.

## Current package boundaries

The migration is deliberately incremental to preserve imports and provider
protocol behavior. `agent/orchestration/` now owns turn construction, atomic
tool-call mechanics, validation/recovery orchestration, completion handling,
and task reports. Stable domain types (`TaskState`, `ProgressSignal`,
`ReasonCode`, `EditFailureType`) remain shallow and directly importable.
`utils/paths.py` owns neutral workspace/path normalization, while
`tools/paths.py` remains a compatibility import. Legacy policy modules have not
all been physically moved yet; compatibility re-exports in `agent/loop.py`
allow semantic tests and consumers to migrate without a flag-day rewrite.

The shared loop now owns only the high-level step budget, phase/context update,
provider call sequencing, provider-message atomicity, and dispatch of results
to the focused components. It no longer implements final-response formatting,
turn construction, tool preparation/execution ordering, or validation and
rollback policy.
