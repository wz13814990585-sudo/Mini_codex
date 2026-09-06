"""Deterministic Git repository awareness for MiniCodex."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


# =============================================================
# Git Repository State
# =============================================================


@dataclass(frozen=True)
class GitRepoState:

    git_available: bool

    is_repo: bool

    branch: str | None

    detached_head: bool

    head_sha: str | None

    dirty: bool

    staged_files: tuple[str, ...] = ()

    modified_files: tuple[str, ...] = ()

    deleted_files: tuple[str, ...] = ()

    untracked_files: tuple[str, ...] = ()

    renamed_files: tuple[str, ...] = ()

    conflicted_files: tuple[str, ...] = ()

    error: str | None = None

    @property
    def changed_files(
        self,
    ) -> tuple[str, ...]:

        files = set()

        files.update(
            self.staged_files
        )

        files.update(
            self.modified_files
        )

        files.update(
            self.deleted_files
        )

        files.update(
            self.untracked_files
        )

        files.update(
            self.renamed_files
        )

        files.update(
            self.conflicted_files
        )

        return tuple(
            sorted(
                files
            )
        )

    def to_dict(
        self,
    ) -> dict:

        return {
            "git_available": (
                self.git_available
            ),
            "is_repo": (
                self.is_repo
            ),
            "branch": (
                self.branch
            ),
            "detached_head": (
                self.detached_head
            ),
            "head_sha": (
                self.head_sha
            ),
            "dirty": (
                self.dirty
            ),
            "staged_files": list(
                self.staged_files
            ),
            "modified_files": list(
                self.modified_files
            ),
            "deleted_files": list(
                self.deleted_files
            ),
            "untracked_files": list(
                self.untracked_files
            ),
            "renamed_files": list(
                self.renamed_files
            ),
            "conflicted_files": list(
                self.conflicted_files
            ),
            "changed_files": list(
                self.changed_files
            ),
            "error": (
                self.error
            ),
        }


# =============================================================
# Git Diff Result
# =============================================================


@dataclass(frozen=True)
class GitDiffResult:

    success: bool

    staged: bool

    path: str | None

    text: str

    total_chars: int

    truncated: bool

    error: str | None = None


# =============================================================
# Task-Level Git Awareness
# =============================================================


@dataclass(frozen=True)
class GitTaskState:

    baseline: GitRepoState

    current: GitRepoState

    agent_touched_files: tuple[str, ...]

    pre_existing_changed_files: tuple[str, ...]

    agent_introduced_files: tuple[str, ...]

    agent_touched_preexisting_files: tuple[str, ...]

    def to_dict(
        self,
    ) -> dict:

        return {
            "baseline": (
                self.baseline
                .to_dict()
            ),
            "current": (
                self.current
                .to_dict()
            ),
            "agent_touched_files": list(
                self.agent_touched_files
            ),
            "pre_existing_changed_files": list(
                self.pre_existing_changed_files
            ),
            "agent_introduced_files": list(
                self.agent_introduced_files
            ),
            "agent_touched_preexisting_files": list(
                self.agent_touched_preexisting_files
            ),
        }


# =============================================================
# Git Repository Inspector
# =============================================================


class GitRepositoryInspector:
    """
    Read-only Git repository inspection.

    This class never performs:

        git add
        git commit
        git checkout
        git reset
        git restore
        git stash

    It only observes repository state.
    """

    CONFLICT_STATES = {
        "DD",
        "AU",
        "UD",
        "UA",
        "DU",
        "AA",
        "UU",
    }

    def __init__(
        self,
        workspace,
    ):

        self.workspace = (
            Path(
                workspace
            )
            .resolve()
        )

    # =========================================================
    # Snapshot
    # =========================================================

    def snapshot(
        self,
    ) -> GitRepoState:

        try:

            repo_check = (
                self._run_git(
                    [
                        "rev-parse",
                        "--is-inside-work-tree",
                    ],
                    check=False,
                )
            )

        except FileNotFoundError:

            return GitRepoState(
                git_available=False,
                is_repo=False,
                branch=None,
                detached_head=False,
                head_sha=None,
                dirty=False,
                error=(
                    "Git executable was not found."
                ),
            )

        except Exception as e:

            return GitRepoState(
                git_available=True,
                is_repo=False,
                branch=None,
                detached_head=False,
                head_sha=None,
                dirty=False,
                error=(
                    f"{type(e).__name__}: "
                    f"{e}"
                ),
            )

        if (
            repo_check.returncode
            != 0
            or (
                repo_check.stdout
                .strip()
                .lower()
                != "true"
            )
        ):

            return GitRepoState(
                git_available=True,
                is_repo=False,
                branch=None,
                detached_head=False,
                head_sha=None,
                dirty=False,
                error=None,
            )

        # =====================================================
        # Branch
        # =====================================================

        branch_result = (
            self._run_git(
                [
                    "symbolic-ref",
                    "--quiet",
                    "--short",
                    "HEAD",
                ],
                check=False,
            )
        )

        branch = (
            branch_result.stdout.strip()
            or None
        )

        # =====================================================
        # HEAD
        # =====================================================

        head_result = (
            self._run_git(
                [
                    "rev-parse",
                    "HEAD",
                ],
                check=False,
            )
        )

        head_sha = (
            head_result.stdout.strip()
            if (
                head_result.returncode
                == 0
            )
            else None
        )

        detached_head = bool(
            branch is None
            and head_sha
        )

        # =====================================================
        # Status
        # =====================================================

        status_result = (
            self._run_git(
                [
                    "status",
                    "--porcelain=v1",
                    "-z",
                    "--untracked-files=all",
                ],
                check=False,
            )
        )

        if (
            status_result.returncode
            != 0
        ):

            return GitRepoState(
                git_available=True,
                is_repo=True,
                branch=branch,
                detached_head=(
                    detached_head
                ),
                head_sha=head_sha,
                dirty=False,
                error=(
                    status_result.stderr.strip()
                    or (
                        "git status failed."
                    )
                ),
            )

        parsed = (
            self._parse_status(
                status_result.stdout
            )
        )

        changed_files = set()

        for values in (
            parsed.values()
        ):

            changed_files.update(
                values
            )

        return GitRepoState(
            git_available=True,
            is_repo=True,
            branch=branch,
            detached_head=(
                detached_head
            ),
            head_sha=head_sha,
            dirty=bool(
                changed_files
            ),
            staged_files=tuple(
                sorted(
                    parsed[
                        "staged"
                    ]
                )
            ),
            modified_files=tuple(
                sorted(
                    parsed[
                        "modified"
                    ]
                )
            ),
            deleted_files=tuple(
                sorted(
                    parsed[
                        "deleted"
                    ]
                )
            ),
            untracked_files=tuple(
                sorted(
                    parsed[
                        "untracked"
                    ]
                )
            ),
            renamed_files=tuple(
                sorted(
                    parsed[
                        "renamed"
                    ]
                )
            ),
            conflicted_files=tuple(
                sorted(
                    parsed[
                        "conflicted"
                    ]
                )
            ),
            error=None,
        )

    # =========================================================
    # Diff
    # =========================================================

    def diff(
        self,
        *,
        path: str | None = None,
        staged: bool = False,
        max_chars: int = 12000,
    ) -> GitDiffResult:

        state = (
            self.snapshot()
        )

        if not (
            state.git_available
        ):

            return GitDiffResult(
                success=False,
                staged=staged,
                path=path,
                text="",
                total_chars=0,
                truncated=False,
                error=(
                    state.error
                    or "Git unavailable."
                ),
            )

        if not (
            state.is_repo
        ):

            return GitDiffResult(
                success=False,
                staged=staged,
                path=path,
                text="",
                total_chars=0,
                truncated=False,
                error=(
                    "Workspace is not a Git repository."
                ),
            )

        normalized_path = None

        if (
            path
            is not None
            and str(
                path
            ).strip()
        ):

            try:

                normalized_path = (
                    self._normalize_path(
                        str(
                            path
                        )
                        .strip()
                    )
                )

            except ValueError as e:

                return GitDiffResult(
                    success=False,
                    staged=staged,
                    path=path,
                    text="",
                    total_chars=0,
                    truncated=False,
                    error=str(
                        e
                    ),
                )

        args = [
            "diff",
            "--no-ext-diff",
            "--no-color",
        ]

        if staged:

            args.append(
                "--cached"
            )

        if (
            normalized_path
            is not None
        ):

            args.extend(
                [
                    "--",
                    normalized_path,
                ]
            )

        result = (
            self._run_git(
                args,
                check=False,
            )
        )

        if (
            result.returncode
            != 0
        ):

            return GitDiffResult(
                success=False,
                staged=staged,
                path=normalized_path,
                text="",
                total_chars=0,
                truncated=False,
                error=(
                    result.stderr.strip()
                    or "git diff failed."
                ),
            )

        text = (
            result.stdout
        )

        total_chars = len(
            text
        )

        safe_max_chars = max(
            1,
            int(
                max_chars
            ),
        )

        truncated = (
            total_chars
            > safe_max_chars
        )

        if truncated:

            text = (
                text[
                    :safe_max_chars
                ]
                + (
                    "\n\n"
                    "[Git diff truncated]"
                )
            )

        return GitDiffResult(
            success=True,
            staged=staged,
            path=normalized_path,
            text=text,
            total_chars=(
                total_chars
            ),
            truncated=(
                truncated
            ),
            error=None,
        )

    # =========================================================
    # Status Parser
    # =========================================================

    def _parse_status(
        self,
        raw: str,
    ) -> dict[
        str,
        set[str],
    ]:

        parsed = {
            "staged": set(),
            "modified": set(),
            "deleted": set(),
            "untracked": set(),
            "renamed": set(),
            "conflicted": set(),
        }

        records = (
            raw.split(
                "\0"
            )
        )

        index = 0

        while (
            index
            < len(
                records
            )
        ):

            record = (
                records[
                    index
                ]
            )

            index += 1

            if not record:

                continue

            if (
                len(
                    record
                )
                < 3
            ):

                continue

            x = (
                record[
                    0
                ]
            )

            y = (
                record[
                    1
                ]
            )

            status = (
                x
                + y
            )

            path = (
                record[
                    3:
                ]
            )

            # =================================================
            # Untracked
            # =================================================

            if (
                status
                == "??"
            ):

                parsed[
                    "untracked"
                ].add(
                    path
                )

                continue

            # =================================================
            # Conflict
            # =================================================

            if (
                status
                in self.CONFLICT_STATES
            ):

                parsed[
                    "conflicted"
                ].add(
                    path
                )

            # =================================================
            # Staged
            # =================================================

            if (
                x
                not in {
                    " ",
                    "?",
                    "!",
                }
            ):

                parsed[
                    "staged"
                ].add(
                    path
                )

            # =================================================
            # Modified
            # =================================================

            if (
                x
                in {
                    "M",
                    "T",
                }
                or y
                in {
                    "M",
                    "T",
                }
            ):

                parsed[
                    "modified"
                ].add(
                    path
                )

            # =================================================
            # Deleted
            # =================================================

            if (
                x
                == "D"
                or y
                == "D"
            ):

                parsed[
                    "deleted"
                ].add(
                    path
                )

            # =================================================
            # Rename / Copy
            #
            # porcelain -z stores the destination path in this
            # record and the second path in the following token.
            # =================================================

            if (
                x
                in {
                    "R",
                    "C",
                }
                or y
                in {
                    "R",
                    "C",
                }
            ):

                parsed[
                    "renamed"
                ].add(
                    path
                )

                if (
                    index
                    < len(
                        records
                    )
                    and records[
                        index
                    ]
                ):

                    index += 1

        return parsed

    # =========================================================
    # Safe Workspace Path
    # =========================================================

    def _normalize_path(
        self,
        path: str,
    ) -> str:

        candidate = (
            (
                self.workspace
                / path
            )
            .resolve()
        )

        try:

            relative = (
                candidate
                .relative_to(
                    self.workspace
                )
            )

        except ValueError as exc:

            raise ValueError(
                "Git path must stay inside "
                "the workspace."
            ) from exc

        return (
            relative
            .as_posix()
        )

    # =========================================================
    # Git Process
    # =========================================================

    def _run_git(
        self,
        args: list[str],
        *,
        check: bool,
    ) -> subprocess.CompletedProcess:

        return subprocess.run(
            [
                "git",
                "-C",
                str(
                    self.workspace
                ),
                *args,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=check,
        )


# =============================================================
# Task Awareness Controller
# =============================================================


class GitAwareness:
    """
    Tracks repository state across one MiniCodex task.

    Important distinction:

        baseline changes
        = changes that already existed when the task started

        agent touched files
        = files MiniCodex successfully edited during this task

    This lets the Harness avoid claiming that every dirty file
    belongs to the Agent.
    """

    def __init__(
        self,
        inspector: GitRepositoryInspector,
    ):

        self.inspector = (
            inspector
        )

        self.workspace = (
            inspector.workspace
        )

        self.baseline = (
            inspector.snapshot()
        )

        self.current = (
            self.baseline
        )

        self._agent_touched_files: set[
            str
        ] = set()

    # =========================================================
    # New Task
    # =========================================================

    def reset_task(
        self,
    ) -> None:

        self._agent_touched_files.clear()

        self.baseline = (
            self.inspector
            .snapshot()
        )

        self.current = (
            self.baseline
        )

    # =========================================================
    # Refresh
    # =========================================================

    def refresh(
        self,
    ) -> GitTaskState:

        self.current = (
            self.inspector
            .snapshot()
        )

        return (
            self.task_state()
        )

    # =========================================================
    # Record Agent Edit
    # =========================================================

    def record_agent_edit(
        self,
        path: str,
    ) -> None:

        normalized = (
            self._normalize_agent_path(
                path
            )
        )

        self._agent_touched_files.add(
            normalized
        )

    # =========================================================
    # Task State
    # =========================================================

    def task_state(
        self,
    ) -> GitTaskState:

        baseline_changed = set(
            self.baseline
            .changed_files
        )

        agent_touched = set(
            self._agent_touched_files
        )

        agent_introduced = (
            agent_touched
            - baseline_changed
        )

        touched_preexisting = (
            agent_touched
            & baseline_changed
        )

        return GitTaskState(
            baseline=(
                self.baseline
            ),
            current=(
                self.current
            ),
            agent_touched_files=tuple(
                sorted(
                    agent_touched
                )
            ),
            pre_existing_changed_files=tuple(
                sorted(
                    baseline_changed
                )
            ),
            agent_introduced_files=tuple(
                sorted(
                    agent_introduced
                )
            ),
            agent_touched_preexisting_files=tuple(
                sorted(
                    touched_preexisting
                )
            ),
        )

    # =========================================================
    # Render For LLM Context
    # =========================================================

    def render(
        self,
    ) -> str:

        task = (
            self.task_state()
        )

        state = (
            task.current
        )

        if not (
            state.git_available
        ):

            return (
                "Git unavailable: "
                f"{state.error or 'unknown error'}"
            )

        if not (
            state.is_repo
        ):

            return (
                "Workspace is not a Git repository."
            )

        branch = (
            state.branch
            or (
                "(detached HEAD)"
                if state.detached_head
                else "(unknown)"
            )
        )

        short_head = (
            state.head_sha[
                :12
            ]
            if state.head_sha
            else "(no HEAD commit)"
        )

        lines = [
            (
                "Git repository state:"
            ),
            (
                f"Branch: {branch}"
            ),
            (
                f"HEAD: {short_head}"
            ),
            (
                f"Dirty: {state.dirty}"
            ),
            (
                "Current changed files: "
                + (
                    ", ".join(
                        state.changed_files
                    )
                    if state.changed_files
                    else "(none)"
                )
            ),
            (
                "Pre-existing task-start changes: "
                + (
                    ", ".join(
                        task.pre_existing_changed_files
                    )
                    if (
                        task.pre_existing_changed_files
                    )
                    else "(none)"
                )
            ),
            (
                "Files touched by MiniCodex this task: "
                + (
                    ", ".join(
                        task.agent_touched_files
                    )
                    if task.agent_touched_files
                    else "(none)"
                )
            ),
            (
                "Agent-introduced files/changes: "
                + (
                    ", ".join(
                        task.agent_introduced_files
                    )
                    if task.agent_introduced_files
                    else "(none)"
                )
            ),
        ]

        if (
            task.agent_touched_preexisting_files
        ):

            lines.append(
                (
                    "WARNING: MiniCodex touched files "
                    "that were already dirty when the "
                    "task started: "
                    + ", ".join(
                        task
                        .agent_touched_preexisting_files
                    )
                )
            )

        return "\n".join(
            lines
        )

    # =========================================================
    # Normalize Agent Path
    # =========================================================

    def _normalize_agent_path(
        self,
        path: str,
    ) -> str:

        candidate = (
            (
                self.workspace
                / str(
                    path
                )
            )
            .resolve()
        )

        try:

            relative = (
                candidate
                .relative_to(
                    self.workspace
                )
            )

        except ValueError:

            return str(
                path
            )

        return (
            relative
            .as_posix()
        )