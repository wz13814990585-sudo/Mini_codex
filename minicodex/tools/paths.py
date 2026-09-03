"""Shared workspace path validation for filesystem tools."""

from pathlib import Path


def resolve_workspace_path(
    workspace: Path,
    path: str,
) -> Path:
    """Resolve a user path and reject access outside the workspace."""
    resolved_workspace = workspace.resolve()
    resolved_path = (resolved_workspace / path).resolve()

    try:
        resolved_path.relative_to(resolved_workspace)
    except ValueError as exc:
        raise ValueError(
            "Access outside the workspace is not allowed."
        ) from exc

    return resolved_path
