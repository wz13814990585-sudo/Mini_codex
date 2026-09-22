# MiniCodex Human-in-the-loop

[简体中文](human-in-the-loop.md) · **English**

Human-in-the-loop is a task-scoped permission protocol between the safety policy and a host UI. It never changes deterministic safety policy; it applies the user's task posture to operations that policy has already allowed.

## Permission modes

| Mode | Caution operations | Side-effecting tools | Final diff |
| --- | --- | --- | --- |
| Review (default) | Wait for a human decision before execution | Run according to safety policy | Keep task-level Accept / Reject |
| Auto | Run policy-allowed operations without approval prompts | Run according to safety policy | Still keep task-level Accept / Reject |
| Read-only | Do not execute | Filter tool schemas and fail closed again at execution | Should produce no Agent edits |

Read-only exposes only registry capabilities marked `read_only`, including file reads, search, and Git inspection. Edits, commands, test processes, browser/service validation processes, and dependency installation are not advertised. Any internal path that still attempts one receives a stable `read_only_mode` denial.

## Execution flow

```text
Tool call → SafetyPolicy
              ├─ SAFE → execute or deny under the current permission mode
              ├─ CAUTION → ApprovalCoordinator in Review mode → allow / deny
              └─ BLOCKED → deny directly; approval cannot override it
```

Typical approval triggers currently include:

- installing or changing dependencies;
- external network access through `curl` or `wget`;
- editing a file that already had uncommitted content when the task started;
- editing a file with a Git conflict.

## User decisions

| Decision | Scope | Result |
| --- | --- | --- |
| Allow once | Current tool call | Execute once; later operations under the same rule still ask |
| Allow for task | Current task and safety rule | Later operations under that rule proceed; a new task clears the grant |
| Deny | Current tool call | Do not execute and return `permission_denied` to the Agent |

Denial never fabricates success. The Agent must find an alternative that does not require the permission or record a concrete blocker. Approval waits time out after five minutes and fail closed. Stop rejects the pending approval before ending the task through the existing cooperative cancellation boundary.

Every request and final resolution emits `approval_requested` and `approval_resolved` Trace events. They contain the redacted tool, rule, target, decision, and resolution source, are saved with the task JSONL, and appear live in the UI activity stream.

## Security boundary

- `BLOCKED` operations such as workspace escape, destructive commands, Git writes, checkpoint bypass, unauthorized edits, and test gaming cannot be unlocked through the UI.
- The UI receives only whitelisted parameters such as `path`, `command`, `package`, `import_name`, `argv`, `url`, and `port`.
- Values pass through secret-key and inline-credential redaction, length limits, and array-count limits.
- An approval ID must match the current pending request; stale or duplicate decisions fail closed.
- Allow for task grants never persist across tasks, processes, or workspaces.

## Current scope

The local Web UI currently hosts approvals and the three permission modes. The CLI retains its existing autonomous caution behavior. Diff review can switch between the complete task change set and one changed file, while Accept / Reject remains task-atomic to avoid unsafe partial checkpoint rollback.
