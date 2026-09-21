# Changelog

All notable changes to MiniCodex are documented in this file.

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
