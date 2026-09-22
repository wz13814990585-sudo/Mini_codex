# MiniCodex local Web workspace

[简体中文](ui.md) · **English**

The Web workspace is a thin interface over the MiniCodex Runtime. It does not reimplement planning, tool calls, safety, validation, or completion; the same `build_agent()` composition root still owns real coding tasks.

> `minicodex ui` ships in the wheel starting with `v0.3.0`.

## Start

```bash
python -m pip install -e ".[test]"
minicodex ui --workspace /path/to/project
```

The default address is `http://127.0.0.1:8765/`, and the browser opens automatically:

```bash
minicodex ui --workspace /path/to/project --port 9000
minicodex ui --workspace /path/to/project --port 0 --no-browser
```

`--port 0` lets the operating system select a free port. You may open and browse the workspace without an API key, but submitting a task requires `MINICODEX_API_KEY` or `DEEPSEEK_API_KEY`.

## Interface areas

| Area | Source of truth | Purpose |
| --- | --- | --- |
| File tree | Workspace-confined read-only file API | Search and select text files; generated directories and credential files are excluded |
| Code / Changes | File API / `GitRepositoryInspector` | View source or the selected file's Git diff |
| Agent Chat | UI task session | Submit natural-language tasks and retain messages for this process |
| Task phases | `TaskState` | Show Inspect, Act, Validate, Done, blocked, and failed states |
| Run activity | `TraceRecorder` | Show model, tool, safety, edit, and validation events; arbitrary shell input is not exposed |
| Operation approval | `ApprovalCoordinator` / `SafetyDecision` | Allow once, allow for the task, or deny before a caution-level operation executes |
| Accept / Reject | Checkpoint lifecycle | Keep changes or safely undo the current task's Agent edits |

The top-right control switches between Chinese and English. It changes interface copy only, never the task text sent to the model.

## Task and review flow

1. Describe the coding goal in Agent Chat.
2. The UI creates a fresh `MiniCodexAgent` and runs it in the background through `AsyncAgentRunner`.
3. The page polls authoritative `TaskState` and structured Trace data. The Agent edits and validates through the same policy as the CLI.
4. If safety classifies an operation as `CAUTION`, the background Agent pauses for approval; ordinary safe operations do not create noisy prompts.
5. The user can allow it once, allow the same rule for this task, or deny it. Denial returns a stable `permission_denied` result to the Agent.
6. If the task produced sealed checkpoints, completion enters `pending` review and blocks the next task.
7. **Accept** keeps the physical workspace changes. **Reject** calls `undo_task()` and restores this task's checkpoints in reverse order.

Reject never runs `git reset` and does not restore unrelated uncommitted changes that predated the task. If the IDE or user changes a file after its checkpoint, rollback reports a conflict and refuses to overwrite it.

The Stop button uses cooperative cancellation at model-call and tool-execution boundaries. Python cannot forcibly terminate an already in-flight synchronous model request, but no next step starts after that call returns.

## Local security boundary

- The service may bind only to `127.0.0.1`, `localhost`, or `::1`.
- Every mutation API requires a random session token generated when the page is served.
- The HTTP Host must be a loopback name; responses set CSP, frame, MIME, and Referrer security headers.
- File paths use the shared workspace boundary, and symlinks never enter the tree.
- `.env`, common credential files, private keys, binaries, and files larger than 2 MiB cannot be previewed.
- The frontend receives only structured events that passed through Trace redaction; API keys are never written into page configuration.

This local UI is not a remote multi-user service. Do not expose it through a reverse proxy or port forwarding. It is also not a container sandbox; command safety remains the responsibility of the existing `SafetyToolExecutor` and `SandboxRunner`.

## Current scope

- One Agent task runs at a time.
- Review applies to the whole task, not each command.
- Pre-execution approval covers `CAUTION` operations only; deterministic `BLOCKED` operations cannot be unlocked by the UI.
- The terminal is a read-only activity stream, not an interactive shell.
- Messages, in-progress state, and Reject checkpoints are process-local; unfinished tasks cannot resume after the service closes.
- Diff reflects the current Git worktree. A file that was already dirty and then edited by the Agent may still contain mixed changes and needs human review.

See the [architecture guide](architecture.en.md) for system boundaries and [Validation Core V2](validation-core-v2.en.md) for validation and completion rules.
