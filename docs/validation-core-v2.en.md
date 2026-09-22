# Validation Core V2

[简体中文](validation-core-v2.md) · **English**

The MiniCodex validation chain has seven authoritative concepts:

1. `TaskRequirement.contract`: a typed, tool-independent machine contract; the natural-language description is presentation only.
2. `ValidationCheck`: one required proof obligation for the current edit revision, explicitly linkable to multiple requirements.
3. `ValidatorResolver`: resolves a tool, arguments, and target only from the contract and registered capabilities; it does not reinterpret natural language.
4. `ValidationExecutor`: lets the Harness execute resolved validation through the existing safety, sandbox, checkpoint, and tool stack.
5. `ValidationEvidence`: exists only after a validator actually executes and always carries an explicit `check_id`.
6. `ValidationLedger`: the only validation source of truth, storing edit revisions, required checks, execution observations, and evidence.
7. `TaskCompletionPolicy`: returns READY only when the ledger proves every required check for the current revision.

The LLM understands the request, inspects source code, and edits files. The Harness resolves and runs deterministic validation mechanics. Once a validation action is resolved, the LLM does not choose its tool again.

Key constraints:

- Non-execution events—invalid arguments, restrictions, safety blocks, duplicate calls, or unavailable tools—record execution observations but never create evidence.
- Anonymous or manually selected diagnostic evidence cannot close a required check.
- Every edit increments the revision and naturally invalidates proof from older revisions.
- Identical contracts may merge into one multi-requirement check; one passing command never proves unrelated requirements implicitly.
- A no-edit task completes only the materialized acceptance checks; without an edit, it does not invent edit-induced regression obligations.
- A missing capability or one bounded target-resolution failure creates an explicit blocker instead of consuming the main loop until step exhaustion.
