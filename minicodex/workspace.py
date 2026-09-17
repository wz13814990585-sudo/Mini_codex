"""Explicit paths for one MiniCodex coding session."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceConfig:
    """Keep the package installation separate from the repository being edited."""

    application_root: Path
    workspace_root: Path
    runtime_root: Path
    sandbox_root: Path
    trace_root: Path
    repository_key: str

    @classmethod
    def create(cls, workspace: str | Path | None = None, *, application_root: str | Path | None = None):
        candidate = Path.cwd() if workspace is None else Path(workspace).expanduser()
        root = candidate.resolve()
        if not root.exists():
            raise ValueError(f"Workspace does not exist: {candidate}")
        if not root.is_dir():
            raise ValueError(f"Workspace is not a directory: {candidate}")
        app_root = Path(application_root or Path(__file__).resolve().parent.parent).resolve()
        identity = sha256(str(root).encode("utf-8")).hexdigest()[:16]
        repository_key = f"{root.name}-{identity}"
        # Runtime traces, memory and sandbox state are agent-owned data, not
        # repository content.  Keeping them outside arbitrary target projects
        # also makes workspace tools unable to discover/edit oracle metadata.
        runtime_root = Path.home() / ".minicodex" / "workspaces" / repository_key
        return cls(app_root, root, runtime_root, runtime_root / "sandbox",
                   runtime_root / "traces", repository_key)
