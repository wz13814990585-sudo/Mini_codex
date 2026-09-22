# Changelog

[简体中文](CHANGELOG.zh-CN.md) · **English**

All notable changes to MiniCodex are documented in this file.

## Unreleased

### Added

- A task-scoped Human-in-the-loop approval coordinator for caution-level operations.
- Web UI decisions for **Allow once**, **Allow for task**, and **Deny**, with bounded redacted operation previews.
- Cooperative cancellation and timeout behavior while an Agent is waiting for approval.
- Per-task **Review**, **Auto**, and **Read-only** permission modes enforced at the tool boundary.
- Persistent Trace audit events for approval requests and resolutions.
- Task-change navigation for reviewing either the complete diff or one changed file at a time.

### Changed

- `SafetyToolExecutor` now pauses UI-hosted caution operations before execution; deterministic hard blocks remain non-overridable.
- Rejected approval requests produce a stable `permission_denied` result so the Agent can choose a safer alternative or report a concrete blocker.
- Read-only mode filters side-effecting tool schemas and independently rejects any attempted edit, process, validation process, or dependency installation at execution time.

## 0.3.0 - 2026-09-22

### Added

- A dependency-free local Web workspace launched with `minicodex ui`.
- File tree and search, code and Git diff views, Agent chat, live task phases, and a Trace activity terminal.
- Task-level Accept / Reject backed by the existing checkpoint rollback engine.
- Loopback-only serving, same-origin mutation tokens, Host validation, security headers, and credential-file preview blocking.

### Fixed

- Async cancellation now wraps the Agent's actual `tool_executor` and exposes a synchronous wait bridge for UI task watchers.

## 0.2.0 - 2026-09-22

### Added

- Product CLI commands: `run`, `chat`, and `doctor`.
- Provider configuration through `MINICODEX_*` variables and CLI overrides.
- Machine-readable environment diagnostics with an opt-in provider connection check.
- Python 3.11–3.13 CI matrix and wheel installation smoke test.
- A copyable local demo workspace.

### Changed

- Model configuration is validated before the agent starts.
- `.env` is loaded from the launch directory instead of the installed package directory.
- Package metadata now includes license, project links, classifiers, and README content.

### Compatibility

- The original `minicodex --prompt "..."` and interactive `minicodex` commands remain supported.
