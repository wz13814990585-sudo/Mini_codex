# MiniCodex Human-in-the-loop

[简体中文](human-in-the-loop.md) · **English**

Human-in-the-loop is a task-scoped approval protocol between the safety policy and a host UI. It handles only operations the Harness has already classified as allowed but caution-worthy; it never changes the safety policy itself.

## Execution flow

```text
Tool call → SafetyPolicy
              ├─ SAFE → execute directly
              ├─ CAUTION → ApprovalCoordinator → allow / deny
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

## Security boundary

- `BLOCKED` operations such as workspace escape, destructive commands, Git writes, checkpoint bypass, unauthorized edits, and test gaming cannot be unlocked through the UI.
- The UI receives only whitelisted parameters such as `path`, `command`, `package`, `import_name`, `argv`, `url`, and `port`.
- Values pass through secret-key and inline-credential redaction, length limits, and array-count limits.
- An approval ID must match the current pending request; stale or duplicate decisions fail closed.
- Allow for task grants never persist across tasks, processes, or workspaces.

## Current scope

The local Web UI is currently the approval host. The CLI retains its existing autonomous caution behavior. Follow-up work includes optional Review / Auto / Read-only modes, approval audit events, and finer-grained diff review.
