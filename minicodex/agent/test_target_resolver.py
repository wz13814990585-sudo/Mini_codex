"""Resolve source artifacts to real pytest targets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..utils.paths import normalize_repo_path, resolve_workspace_path


@dataclass(frozen=True)
class TestTargetResolution:
    selected_path: str | None
    source_path: str | None
    confidence: str
    reason: str
    acceptance_supported: bool


class TestTargetResolver:
    """Find an existing test without ever treating source as acceptance."""

    __test__ = False

    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()

    def resolve(self, source_paths: tuple[str, ...]) -> TestTargetResolution:
        normalized = tuple(
            dict.fromkeys(
                normalize_repo_path(str(path).strip())
                for path in source_paths
                if str(path).strip()
            )
        )
        for source in normalized:
            if self.is_test_path(source) and self._exists(source):
                return TestTargetResolution(
                    source, source, "high", "The requested artifact is an existing pytest target.", True
                )

        for source in normalized:
            if not source.lower().endswith(".py"):
                continue
            for candidate in self._candidates(source):
                if self._exists(candidate):
                    return TestTargetResolution(
                        candidate,
                        source,
                        "high",
                        f"Mapped source {source} to existing test {candidate}.",
                        True,
                    )

        for directory in ("minicodex/tests", "tests"):
            if (self.workspace / directory).is_dir():
                return TestTargetResolution(
                    directory,
                    normalized[0] if normalized else None,
                    "low",
                    "No focused test was found; only a regression directory is available.",
                    False,
                )

        return TestTargetResolution(
            None,
            normalized[0] if normalized else None,
            "none",
            "No existing pytest target could be resolved for the requested source.",
            False,
        )

    @staticmethod
    def is_test_path(path: str) -> bool:
        candidate = Path(str(path).split("::", 1)[0])
        name = candidate.name.lower()
        return (
            "tests" in {part.lower() for part in candidate.parts}
            or name.startswith("test_")
            or name.endswith("_test.py")
        )

    def _candidates(self, source: str) -> tuple[str, ...]:
        path = Path(source)
        stem = path.stem
        candidates = [
            path.with_name(f"test_{stem}.py"),
            path.parent / "tests" / f"test_{stem}.py",
            Path("minicodex/tests") / f"test_{stem}.py",
            Path("tests") / f"test_{stem}.py",
        ]
        return tuple(dict.fromkeys(candidate.as_posix() for candidate in candidates))

    def _exists(self, relative: str) -> bool:
        try:
            candidate = resolve_workspace_path(self.workspace, relative.split("::", 1)[0])
        except (ValueError, OSError):
            return False
        return candidate.is_file()
