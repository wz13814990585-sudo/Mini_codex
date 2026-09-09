"""Deterministic, manifest-aware Python dependency resolution policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib


_SPEC_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class DependencyResolution:
    package: str
    declared: bool
    install_allowed: bool
    standalone: bool
    manifests: tuple[str, ...]
    preferred_manifest: str | None
    action: str
    reason: str


class DependencyResolver:
    """Inspect existing manifests before permitting environment mutation."""

    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()

    def resolve(
        self,
        package: str,
        *,
        target_paths: tuple[str, ...] = (),
    ) -> DependencyResolution:
        name = self._normalize_name(package)
        manifests = self._manifest_paths()
        standalone = bool(target_paths) and all(
            str(path).replace("\\", "/").startswith(("try_code/", "examples/"))
            for path in target_paths
        )
        declared_names: set[str] = set()
        for manifest in manifests:
            declared_names.update(self._declared_names(manifest))
        declared = name in declared_names
        relative = tuple(path.relative_to(self.workspace).as_posix() for path in manifests)
        preferred = self._preferred_manifest(relative)

        if declared:
            return DependencyResolution(
                package=package,
                declared=True,
                install_allowed=True,
                standalone=standalone,
                manifests=relative,
                preferred_manifest=preferred,
                action="install_declared_dependency",
                reason="The dependency is already declared by the project.",
            )
        if standalone or not manifests:
            return DependencyResolution(
                package=package,
                declared=False,
                install_allowed=True,
                standalone=True,
                manifests=relative,
                preferred_manifest=preferred,
                action="install_without_manifest_mutation",
                reason=(
                    "This is an isolated artifact with no applicable project "
                    "dependency declaration requirement."
                ),
            )
        return DependencyResolution(
            package=package,
            declared=False,
            install_allowed=False,
            standalone=False,
            manifests=relative,
            preferred_manifest=preferred,
            action="update_manifest_first",
            reason=(
                f"'{package}' is not declared. Update {preferred or 'the existing manifest'} "
                "with a checkpointed edit before installing it."
            ),
        )

    def _manifest_paths(self) -> list[Path]:
        candidates = [self.workspace / "pyproject.toml"]
        candidates.extend(sorted(self.workspace.glob("requirements*.txt")))
        return [path for path in candidates if path.is_file()]

    def _declared_names(self, path: Path) -> set[str]:
        if path.name.startswith("requirements"):
            names = set()
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.split("#", 1)[0].strip()
                if stripped and not stripped.startswith(("-", "http:", "https:")):
                    names.add(self._normalize_name(stripped))
            return names
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return set()
        values = list(data.get("project", {}).get("dependencies", []) or [])
        optional = data.get("project", {}).get("optional-dependencies", {}) or {}
        for group in optional.values():
            values.extend(group or [])
        poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}
        values.extend(poetry.keys())
        return {self._normalize_name(str(value)) for value in values}

    @staticmethod
    def _preferred_manifest(paths: tuple[str, ...]) -> str | None:
        return next((path for path in paths if path == "pyproject.toml"), paths[0] if paths else None)

    @staticmethod
    def _normalize_name(spec: str) -> str:
        match = _SPEC_NAME.match(str(spec).strip())
        name = match.group(0) if match else str(spec).strip()
        return re.sub(r"[-_.]+", "-", name).casefold()
