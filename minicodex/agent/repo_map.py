import os
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

    Stage 6 only provides repository structure.

    RepoMap does not read file contents and does not
    extract classes, functions, or other code symbols.
    Symbol awareness belongs to Stage 7.
    """

    workspace: str | Path = "."
    max_depth: int = 4
    max_files: int = 200

    # =========================================================
    # Build
    # =========================================================

    def build(
        self,
    ) -> str:
        """
        Build and return the current repository structure.
        """

        root = Path(
            self.workspace
        ).resolve()

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

        emitted_directories = set()

        for relative_path in files:

            parts = (
                relative_path.parts
            )

            # =================================================
            # Parent Directories
            # =================================================

            for depth in range(
                len(parts) - 1
            ):

                directory_parts = (
                    parts[:depth + 1]
                )

                directory_key = tuple(
                    directory_parts
                )

                if (
                    directory_key
                    in emitted_directories
                ):
                    continue

                emitted_directories.add(
                    directory_key
                )

                indent = (
                    "    " * depth
                )

                lines.append(
                    f"{indent}"
                    f"{parts[depth]}/"
                )

            # =================================================
            # File
            # =================================================

            file_depth = (
                len(parts) - 1
            )

            indent = (
                "    " * file_depth
            )

            lines.append(
                f"{indent}"
                f"{parts[-1]}"
            )

        # =====================================================
        # Truncation Notice
        # =====================================================

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
        """
        Walk the workspace while pruning irrelevant
        directories before descending into them.
        """

        results = []

        for (
            current_root,
            dir_names,
            file_names,
        ) in os.walk(
            root
        ):

            current_path = Path(
                current_root
            )

            relative_root = (
                current_path.relative_to(
                    root
                )
            )

            if (
                relative_root
                == Path(".")
            ):

                current_depth = 0

            else:

                current_depth = len(
                    relative_root.parts
                )

            # =================================================
            # Directory Pruning
            # =================================================

            if (
                current_depth
                >= self.max_depth
            ):

                # Important:
                # modifying dir_names in-place tells
                # os.walk not to descend any further.
                dir_names[:] = []

            else:

                # Remove ignored directories BEFORE
                # os.walk enters them.
                dir_names[:] = sorted(
                    [
                        directory
                        for directory
                        in dir_names
                        if (
                            directory
                            not in DEFAULT_IGNORED_DIRS
                        )
                    ],
                    key=str.lower,
                )

            # =================================================
            # Files
            # =================================================

            for file_name in sorted(
                file_names,
                key=str.lower,
            ):

                path = (
                    current_path
                    / file_name
                )

                relative = (
                    path.relative_to(
                        root
                    )
                )

                # max_depth counts directory depth from the
                # workspace root. A file's parent depth is
                # len(parts) - 1, so a/b/two.py is depth 2.
                if (
                    len(relative.parts) - 1
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

                    return sorted(
                        results,
                        key=self._sort_key,
                    )

        return sorted(
            results,
            key=self._sort_key,
        )

    # =========================================================
    # Sort
    # =========================================================

    @staticmethod
    def _sort_key(
        path: Path,
    ) -> tuple:

        return tuple(
            part.lower()
            for part
            in path.parts
        )