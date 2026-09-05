from dataclasses import dataclass
from pathlib import Path


DEFAULT_IGNORED_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
}


@dataclass
class RepoMap:
    """
    Build a compact structural map of the workspace.

    RepoMap intentionally contains only repository
    structure in Stage 6.

    It does not inspect symbols or full file contents.
    """

    workspace: str = "."
    max_depth: int = 4
    max_files: int = 200

    def build(
        self,
    ) -> str:

        root = (
            Path(self.workspace)
            .resolve()
        )

        if not root.exists():

            return (
                "Repository map unavailable: "
                "workspace does not exist."
            )

        if not root.is_dir():

            return (
                "Repository map unavailable: "
                "workspace is not a directory."
            )

        files = self._collect_files(
            root
        )

        if not files:

            return (
                "Repository appears empty."
            )

        lines = [
            "Repository structure:"
        ]

        previous_parts = []

        for relative_path in files:

            parts = list(
                relative_path.parts
            )

            # =============================================
            # Directory Lines
            # =============================================

            common_prefix = 0

            while (
                common_prefix
                < len(previous_parts)
                and common_prefix
                < len(parts) - 1
                and previous_parts[
                    common_prefix
                ]
                == parts[
                    common_prefix
                ]
            ):
                common_prefix += 1

            for depth in range(
                common_prefix,
                len(parts) - 1,
            ):

                indent = (
                    "    " * depth
                )

                lines.append(
                    f"{indent}"
                    f"{parts[depth]}/"
                )

            # =============================================
            # File Line
            # =============================================

            file_depth = (
                len(parts)
                - 1
            )

            indent = (
                "    " * file_depth
            )

            lines.append(
                f"{indent}"
                f"{parts[-1]}"
            )

            previous_parts = (
                parts[:-1]
            )

        if (
            len(files)
            >= self.max_files
        ):

            lines.append(
                (
                    "... repository map "
                    f"limited to "
                    f"{self.max_files} files."
                )
            )

        return "\n".join(
            lines
        )

    # =========================================================
    # File Collection
    # =========================================================

    def _collect_files(
        self,
        root: Path,
    ) -> list[Path]:

        results = []

        for path in root.rglob(
            "*"
        ):

            if not path.is_file():
                continue

            relative = (
                path.relative_to(
                    root
                )
            )

            if self._should_ignore(
                relative
            ):
                continue

            if (
                len(relative.parts)
                > self.max_depth
            ):
                continue

            results.append(
                relative
            )

            if (
                len(results)
                >= self.max_files
            ):
                break

        return sorted(
            results,
            key=lambda item: (
                tuple(
                    part.lower()
                    for part
                    in item.parts
                )
            ),
        )

    # =========================================================
    # Ignore Policy
    # =========================================================

    def _should_ignore(
        self,
        relative_path: Path,
    ) -> bool:

        return any(
            part in DEFAULT_IGNORED_DIRS
            for part
            in relative_path.parts
        )