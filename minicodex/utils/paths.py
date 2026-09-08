"""Central, domain-neutral repository path handling."""

from __future__ import annotations

from pathlib import Path


def normalize_repo_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").removeprefix("./")


def is_within_workspace(workspace: str | Path, path: str | Path) -> bool:
    root = Path(workspace).resolve()
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_workspace_path(workspace: str | Path, path: str | Path) -> Path:
    root = Path(workspace).resolve()
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Access outside the workspace is not allowed.") from exc
    return resolved


def to_repo_relative(workspace: str | Path, path: str | Path) -> str:
    root = Path(workspace).resolve()
    return resolve_workspace_path(root, path).relative_to(root).as_posix()


def same_repo_path(workspace: str | Path, left: str | Path, right: str | Path) -> bool:
    return resolve_workspace_path(workspace, left) == resolve_workspace_path(workspace, right)
