# MiniCodex control-plane architecture

MiniCodex uses one shared agent loop for FAST, STANDARD, and COMPLEX work. The
router selects an `ExecutionPolicy`; it does not select a separate runtime.
Mode differences are limited to planning, budgets, exposed tools, context,
recovery, and proportional regression requirements.

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
source. It compares `TaskState.progress_key()` snapshots, so repeated reads,
searches, repository-map refreshes, and identical observations do not count as
meaningful progress.

## Execution flow

The shared loop performs the following sequence:

1. Refresh the task-state projection and build mode-filtered context.
2. Ask the model using mode-filtered tool schemas.
3. Apply deterministic batch restrictions from `tool_batch.py`.
4. Execute tools through safety, checkpoint, and reliable execution wrappers.
5. Normalize edit and validation evidence and update the phase.
6. Apply validation/completion transitions from
   `orchestration_transitions.py`.
7. Close every skipped provider tool call before restarting or finishing.

FAST is planless and immediately completes when targeted acceptance evidence
passes. STANDARD uses a short outcome plan and focused regression. COMPLEX adds
long-term memory, broader recovery, limited replanning, and full regression.

## Edit, dependency, and validation reliability

Checkpointed edit tools return structured metadata including `path`,
`checkpoint_id`, `changed`, and `edit_kind`. Exact patch, line, and symbol
guards return `failure_type=stale_context` instead of an opaque exception.
`EditRetryPolicy` then permits exactly one target read and one edit retry.

`DependencyResolver` reads `pyproject.toml` and `requirements*.txt` before a
Python install. Declared dependencies may be installed. Undeclared project
dependencies require a manifest edit first. Isolated examples avoid unrelated
manifest mutation.

`ValidationSelector` recommends one proportional validator from artifact type.
Static HTML uses `validate_static_web`; Python uses focused pytest; other
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
