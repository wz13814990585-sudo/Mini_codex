"""Deterministic safety and permission policy for MiniCodex."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
import shlex


# =============================================================
# Safety Levels
# =============================================================


class SafetyLevel(
    str,
    Enum,
):

    SAFE = "safe"

    CAUTION = "caution"

    BLOCKED = "blocked"


# =============================================================
# Safety Decision
# =============================================================


@dataclass(
    frozen=True
)
class SafetyDecision:

    level: SafetyLevel

    allowed: bool

    reason: str

    rule: str

    tool_name: str

    path: str | None = None

    command: str | None = None

    @property
    def requires_attention(
        self,
    ) -> bool:

        return (
            self.level
            == SafetyLevel.CAUTION
        )

    def to_dict(
        self,
    ) -> dict:

        return {
            "level": (
                self.level.value
            ),
            "allowed": (
                self.allowed
            ),
            "reason": (
                self.reason
            ),
            "rule": (
                self.rule
            ),
            "tool_name": (
                self.tool_name
            ),
            "path": (
                self.path
            ),
            "command": (
                self.command
            ),
            "requires_attention": (
                self.requires_attention
            ),
        }


# =============================================================
# Safety Policy
# =============================================================


class SafetyPolicy:
    """
    Deterministic Harness safety policy.

    Safety decisions belong to the Harness, not the LLM.

    Stage 12 is NOT a full OS sandbox.

    It protects the deterministic tool-call boundary.

    Full process isolation belongs to the later Sandbox stage.
    """

    EDIT_TOOL_NAMES = {
        "patch_file",
        "replace_lines",
        "replace_symbol",
        "write_file",
    }

    # =========================================================
    # Executable Name Groups
    # =========================================================

    BLOCKED_EXECUTABLES = {
        "rm": "destructive_rm",
        "sudo": "privilege_escalation",
        "shutdown": "system_shutdown",
        "reboot": "system_shutdown",
        "poweroff": "system_shutdown",
        "halt": "system_shutdown",
        "mkfs": "disk_operation",
        "fdisk": "disk_operation",
        "parted": "disk_operation",
        "chmod": "ownership_change",
        "chown": "ownership_change",
        "chgrp": "ownership_change",
        "kill": "process_termination",
        "killall": "process_termination",
        "pkill": "process_termination",
        "mv": "direct_file_mutation",
        "cp": "direct_file_mutation",
        "touch": "direct_file_mutation",
        "truncate": "direct_file_mutation",
        "mkdir": "direct_file_mutation",
        "rmdir": "direct_file_mutation",
        "ln": "direct_file_mutation",
        "tee": "tee_write",
    }

    NETWORK_EXECUTABLES = {
        "curl",
        "wget",
    }

    # =========================================================
    # Git Mutation
    # =========================================================

    GIT_MUTATING_SUBCOMMANDS = {
        "add",
        "commit",
        "reset",
        "clean",
        "checkout",
        "restore",
        "stash",
        "switch",
        "merge",
        "rebase",
        "cherry-pick",
        "revert",
        "push",
        "pull",
    }

    # =========================================================
    # Package Installation
    # =========================================================

    PACKAGE_INSTALL_PATTERN = re.compile(
        r"\b("
        r"pip(?:3)?\s+install|"
        r"python(?:3)?\s+-m\s+pip\s+install|"
        r"npm\s+install|"
        r"pnpm\s+install|"
        r"yarn\s+add|"
        r"brew\s+install|"
        r"apt(?:-get)?\s+install"
        r")\b",
        re.IGNORECASE,
    )

    # =========================================================
    # Other Mutating Patterns
    # =========================================================

    SED_IN_PLACE_PATTERN = re.compile(
        r"\bsed\s+[^;&|]*"
        r"(?:-i|--in-place)",
        re.IGNORECASE,
    )

    PERL_IN_PLACE_PATTERN = re.compile(
        r"\bperl\s+[^;&|]*"
        r"-[A-Za-z]*i[A-Za-z]*",
        re.IGNORECASE,
    )

    RAW_DISK_WRITE_PATTERN = re.compile(
        r"\bdd\b.*\bof\s*=",
        re.IGNORECASE,
    )

    # =========================================================
    # Constructor
    # =========================================================

    def __init__(
        self,
        *,
        workspace,
        git_awareness=None,
    ):

        self.workspace = (
            Path(
                workspace
            )
            .resolve()
        )

        self.git_awareness = (
            git_awareness
        )

    # =========================================================
    # Public Assessment
    # =========================================================

    def assess(
        self,
        tool_name: str,
        arguments: dict,
    ) -> SafetyDecision:

        if tool_name == "install_python_package":
            return SafetyDecision(
                level=SafetyLevel.CAUTION,
                allowed=True,
                reason=(
                    "Tool installs a Python dependency into the "
                    "MiniCodex interpreter environment."
                ),
                rule="dependency_install",
                tool_name=tool_name,
            )

        if (
            tool_name
            == "run_command"
        ):

            return (
                self._assess_command(
                    tool_name=tool_name,
                    arguments=arguments,
                )
            )

        if (
            tool_name
            in self.EDIT_TOOL_NAMES
        ):

            return (
                self._assess_edit(
                    tool_name=tool_name,
                    arguments=arguments,
                )
            )

        return SafetyDecision(
            level=(
                SafetyLevel.SAFE
            ),
            allowed=True,
            reason=(
                "Tool does not match a "
                "restricted Stage 12 operation."
            ),
            rule=(
                "default_safe"
            ),
            tool_name=tool_name,
        )

    # =========================================================
    # Edit Assessment
    # =========================================================

    def _assess_edit(
        self,
        *,
        tool_name: str,
        arguments: dict,
    ) -> SafetyDecision:

        path_value = (
            arguments
            .get(
                "path"
            )
        )

        if (
            path_value
            is None
            or not str(
                path_value
            ).strip()
        ):

            return SafetyDecision(
                level=(
                    SafetyLevel.SAFE
                ),
                allowed=True,
                reason=(
                    "No path was available for "
                    "safety classification. "
                    "Downstream edit validation "
                    "will handle the call."
                ),
                rule=(
                    "defer_missing_path"
                ),
                tool_name=tool_name,
            )

        raw_path = (
            str(
                path_value
            )
            .strip()
        )

        normalized = (
            self._normalize_workspace_path(
                raw_path
            )
        )

        # =====================================================
        # Workspace Escape
        # =====================================================

        if (
            normalized
            is None
        ):

            return SafetyDecision(
                level=(
                    SafetyLevel.BLOCKED
                ),
                allowed=False,
                reason=(
                    "The edit target resolves "
                    "outside the workspace."
                ),
                rule=(
                    "workspace_escape"
                ),
                tool_name=tool_name,
                path=raw_path,
            )

        # =====================================================
        # .git Internals
        # =====================================================

        if (
            normalized
            == ".git"
            or normalized.startswith(
                ".git/"
            )
        ):

            return SafetyDecision(
                level=(
                    SafetyLevel.BLOCKED
                ),
                allowed=False,
                reason=(
                    "Direct modification of Git "
                    "internal metadata is not allowed."
                ),
                rule=(
                    "git_metadata_protection"
                ),
                tool_name=tool_name,
                path=normalized,
            )

        # =====================================================
        # Pre-existing User Work
        # =====================================================

        baseline_changed = (
            self._baseline_changed_files()
        )

        if (
            normalized
            in baseline_changed
        ):

            return SafetyDecision(
                level=(
                    SafetyLevel.CAUTION
                ),
                allowed=True,
                reason=(
                    "This file was already dirty "
                    "when the task started and may "
                    "contain pre-existing user work."
                ),
                rule=(
                    "preexisting_user_change"
                ),
                tool_name=tool_name,
                path=normalized,
            )

        # =====================================================
        # Merge Conflict
        # =====================================================

        current_conflicts = (
            self._current_conflicted_files()
        )

        if (
            normalized
            in current_conflicts
        ):

            return SafetyDecision(
                level=(
                    SafetyLevel.CAUTION
                ),
                allowed=True,
                reason=(
                    "The target file currently "
                    "has a Git conflict."
                ),
                rule=(
                    "git_conflict"
                ),
                tool_name=tool_name,
                path=normalized,
            )

        return SafetyDecision(
            level=(
                SafetyLevel.SAFE
            ),
            allowed=True,
            reason=(
                "Edit stays inside the workspace "
                "and does not target protected "
                "Git metadata or known "
                "pre-existing user work."
            ),
            rule=(
                "workspace_edit"
            ),
            tool_name=tool_name,
            path=normalized,
        )

    # =========================================================
    # Command Assessment
    # =========================================================

    def _assess_command(
        self,
        *,
        tool_name: str,
        arguments: dict,
    ) -> SafetyDecision:

        command_value = (
            arguments
            .get(
                "command"
            )
        )

        if (
            command_value
            is None
        ):

            return SafetyDecision(
                level=(
                    SafetyLevel.SAFE
                ),
                allowed=True,
                reason=(
                    "No command was available "
                    "for safety classification."
                ),
                rule=(
                    "defer_missing_command"
                ),
                tool_name=tool_name,
            )

        command = (
            str(
                command_value
            )
            .strip()
        )

        if not command:

            return SafetyDecision(
                level=(
                    SafetyLevel.SAFE
                ),
                allowed=True,
                reason=(
                    "Empty command contains "
                    "no operation."
                ),
                rule=(
                    "empty_command"
                ),
                tool_name=tool_name,
                command=command,
            )

        # =====================================================
        # Shell Redirection Guard
        # =====================================================

        if (
            self._contains_unsafe_redirection(
                command
            )
        ):

            return SafetyDecision(
                level=(
                    SafetyLevel.BLOCKED
                ),
                allowed=False,
                reason=(
                    "Shell output redirection may "
                    "write files outside the "
                    "checkpointed edit pipeline."
                ),
                rule=(
                    "checkpoint_bypass_redirection"
                ),
                tool_name=tool_name,
                command=command,
            )

        # =====================================================
        # Explicit Known Mutations
        # =====================================================

        if (
            self.RAW_DISK_WRITE_PATTERN
            .search(
                command
            )
        ):

            return (
                self._blocked_command(
                    tool_name=tool_name,
                    command=command,
                    rule=(
                        "raw_disk_write"
                    ),
                )
            )

        if (
            self.SED_IN_PLACE_PATTERN
            .search(
                command
            )
        ):

            return (
                self._blocked_command(
                    tool_name=tool_name,
                    command=command,
                    rule=(
                        "sed_in_place"
                    ),
                )
            )

        if (
            self.PERL_IN_PLACE_PATTERN
            .search(
                command
            )
        ):

            return (
                self._blocked_command(
                    tool_name=tool_name,
                    command=command,
                    rule=(
                        "perl_in_place"
                    ),
                )
            )

        # =====================================================
        # Parse Shell Segments
        #
        # This is intentionally not a full shell parser.
        # It gives deterministic awareness of ordinary command
        # segments while normalizing:
        #
        #     /bin/rm    → rm
        #     /usr/bin/git → git
        # =====================================================

        segments = (
            self._command_segments(
                command
            )
        )

        for tokens in segments:

            if not tokens:

                continue

            executable = (
                self._executable_name(
                    tokens[
                        0
                    ]
                )
            )

            # =================================================
            # Blocked Executables
            # =================================================

            blocked_rule = (
                self.BLOCKED_EXECUTABLES
                .get(
                    executable
                )
            )

            if (
                blocked_rule
                is not None
            ):

                return (
                    self._blocked_command(
                        tool_name=tool_name,
                        command=command,
                        rule=(
                            blocked_rule
                        ),
                    )
                )

            # =================================================
            # Git
            # =================================================

            if (
                executable
                == "git"
            ):

                git_decision = (
                    self._assess_git_tokens(
                        tool_name=tool_name,
                        command=command,
                        tokens=tokens,
                    )
                )

                if (
                    git_decision
                    is not None
                ):

                    return (
                        git_decision
                    )

            # =================================================
            # Network
            # =================================================

            if (
                executable
                in self.NETWORK_EXECUTABLES
            ):

                return SafetyDecision(
                    level=(
                        SafetyLevel.CAUTION
                    ),
                    allowed=True,
                    reason=(
                        "Command performs external "
                        "network access."
                    ),
                    rule=(
                        "network_access"
                    ),
                    tool_name=tool_name,
                    command=command,
                )

        # =====================================================
        # Dependency Installation
        # =====================================================

        if (
            self.PACKAGE_INSTALL_PATTERN
            .search(
                command
            )
        ):

            return SafetyDecision(
                level=(
                    SafetyLevel.CAUTION
                ),
                allowed=True,
                reason=(
                    "Command installs or modifies "
                    "software dependencies."
                ),
                rule=(
                    "dependency_install"
                ),
                tool_name=tool_name,
                command=command,
            )

        return SafetyDecision(
            level=(
                SafetyLevel.SAFE
            ),
            allowed=True,
            reason=(
                "Command does not match a known "
                "Stage 12 blocked or caution rule."
            ),
            rule=(
                "command_safe"
            ),
            tool_name=tool_name,
            command=command,
        )

    # =========================================================
    # Git Assessment
    # =========================================================

    def _assess_git_tokens(
        self,
        *,
        tool_name: str,
        command: str,
        tokens: list[str],
    ) -> SafetyDecision | None:

        if (
            len(
                tokens
            )
            < 2
        ):

            return None

        index = 1

        # Skip common global Git options.
        while (
            index
            < len(
                tokens
            )
        ):

            token = (
                tokens[
                    index
                ]
            )

            if (
                token
                == "-C"
            ):

                index += 2

                continue

            if (
                token.startswith(
                    "--git-dir="
                )
                or token.startswith(
                    "--work-tree="
                )
                or token.startswith(
                    "--namespace="
                )
            ):

                index += 1

                continue

            if (
                token.startswith(
                    "-"
                )
            ):

                index += 1

                continue

            break

        if (
            index
            >= len(
                tokens
            )
        ):

            return None

        subcommand = (
            tokens[
                index
            ]
            .lower()
        )

        if (
            subcommand
            in self.GIT_MUTATING_SUBCOMMANDS
        ):

            return SafetyDecision(
                level=(
                    SafetyLevel.BLOCKED
                ),
                allowed=False,
                reason=(
                    "Mutating Git operations are "
                    "blocked through run_command."
                ),
                rule=(
                    "git_mutation"
                ),
                tool_name=tool_name,
                command=command,
            )

        # =====================================================
        # git branch destructive modes
        # =====================================================

        if (
            subcommand
            == "branch"
        ):

            remaining = (
                tokens[
                    index + 1:
                ]
            )

            destructive = {
                "-d",
                "-D",
                "-m",
                "-M",
                "--delete",
                "--move",
            }

            if any(
                token in destructive
                for token
                in remaining
            ):

                return SafetyDecision(
                    level=(
                        SafetyLevel.BLOCKED
                    ),
                    allowed=False,
                    reason=(
                        "Destructive Git branch "
                        "mutation is blocked."
                    ),
                    rule=(
                        "git_reference_mutation"
                    ),
                    tool_name=tool_name,
                    command=command,
                )

        # =====================================================
        # git tag deletion
        # =====================================================

        if (
            subcommand
            == "tag"
        ):

            remaining = (
                tokens[
                    index + 1:
                ]
            )

            if any(
                token
                in {
                    "-d",
                    "--delete",
                }
                for token
                in remaining
            ):

                return SafetyDecision(
                    level=(
                        SafetyLevel.BLOCKED
                    ),
                    allowed=False,
                    reason=(
                        "Destructive Git tag "
                        "mutation is blocked."
                    ),
                    rule=(
                        "git_reference_mutation"
                    ),
                    tool_name=tool_name,
                    command=command,
                )

        return None

    # =========================================================
    # Command Segments
    # =========================================================

    def _command_segments(
        self,
        command: str,
    ) -> list[
        list[str]
    ]:

        # Split ordinary compound commands:
        #
        #   a && b
        #   a ; b
        #   a | b
        #
        # This is conservative and intentionally not a complete
        # shell grammar.
        raw_segments = re.split(
            r"(?:&&|\|\||[;|])",
            command,
        )

        segments = []

        for raw_segment in (
            raw_segments
        ):

            text = (
                raw_segment
                .strip()
            )

            if not text:

                continue

            try:

                tokens = (
                    shlex.split(
                        text
                    )
                )

            except ValueError:

                # If shell parsing is malformed, do not crash
                # the safety layer. Fallback to whitespace.
                tokens = (
                    text.split()
                )

            if tokens:

                segments.append(
                    tokens
                )

        return segments

    # =========================================================
    # Executable Normalization
    # =========================================================

    @staticmethod
    def _executable_name(
        executable: str,
    ) -> str:

        return (
            Path(
                executable
            )
            .name
            .lower()
        )

    # =========================================================
    # Blocked Command Helper
    # =========================================================

    @staticmethod
    def _blocked_command(
        *,
        tool_name: str,
        command: str,
        rule: str,
    ) -> SafetyDecision:

        return SafetyDecision(
            level=(
                SafetyLevel.BLOCKED
            ),
            allowed=False,
            reason=(
                "Command matched a "
                "deterministically blocked "
                f"safety rule: {rule}."
            ),
            rule=rule,
            tool_name=tool_name,
            command=command,
        )

    # =========================================================
    # Unsafe Shell Redirection
    # =========================================================

    @staticmethod
    def _contains_unsafe_redirection(
        command: str,
    ) -> bool:
        """
        Detect shell output writes that bypass checkpoint tools.

        Block:

            > file
            >> file
            2> error.log

        Allow:

            >/dev/null
            2>/dev/null
            2>&1
            1>&2
        """

        index = 0

        length = len(
            command
        )

        while (
            index
            < length
        ):

            char = (
                command[
                    index
                ]
            )

            if (
                char
                != ">"
            ):

                index += 1

                continue

            # =================================================
            # File-descriptor duplication:
            #
            # 2>&1
            # 1>&2
            #
            # This does NOT write a filesystem path.
            # =================================================

            next_index = (
                index
                + 1
            )

            if (
                next_index
                < length
                and command[
                    next_index
                ]
                == ">"
            ):

                next_index += 1

            while (
                next_index
                < length
                and command[
                    next_index
                ].isspace()
            ):

                next_index += 1

            if (
                next_index
                < length
                and command[
                    next_index
                ]
                == "&"
            ):

                index = (
                    next_index
                    + 1
                )

                continue

            # =================================================
            # Extract Redirect Target
            # =================================================

            target_start = (
                next_index
            )

            while (
                next_index
                < length
                and not command[
                    next_index
                ].isspace()
                and command[
                    next_index
                ]
                not in {
                    ";",
                    "|",
                    "&",
                }
            ):

                next_index += 1

            target = (
                command[
                    target_start:
                    next_index
                ]
                .strip(
                    "\"'"
                )
            )

            if not target:

                return True

            if (
                target
                != "/dev/null"
            ):

                return True

            index = (
                next_index
            )

        return False

    # =========================================================
    # Git Awareness Helpers
    # =========================================================

    def _baseline_changed_files(
        self,
    ) -> set[str]:

        if (
            self.git_awareness
            is None
        ):

            return set()

        baseline = getattr(
            self.git_awareness,
            "baseline",
            None,
        )

        if (
            baseline
            is None
        ):

            return set()

        return set(
            baseline.changed_files
        )

    def _current_conflicted_files(
        self,
    ) -> set[str]:

        if (
            self.git_awareness
            is None
        ):

            return set()

        current = getattr(
            self.git_awareness,
            "current",
            None,
        )

        if (
            current
            is None
        ):

            return set()

        return set(
            current.conflicted_files
        )

    # =========================================================
    # Workspace Path
    # =========================================================

    def _normalize_workspace_path(
        self,
        path: str,
    ) -> str | None:

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

        except ValueError:

            return None

        return (
            relative
            .as_posix()
        )

    # =========================================================
    # Render
    # =========================================================

    def render(
        self,
    ) -> str:

        preexisting = (
            sorted(
                self._baseline_changed_files()
            )
        )

        return "\n".join(
            [
                "Safety policy:",
                (
                    "SAFE: execute automatically."
                ),
                (
                    "CAUTION: execute but preserve "
                    "risk metadata."
                ),
                (
                    "BLOCKED: do not execute."
                ),
                (
                    "Direct edits outside the "
                    "workspace are blocked."
                ),
                (
                    "Direct writes to .git metadata "
                    "are blocked."
                ),
                (
                    "Destructive Git and direct "
                    "filesystem mutation through "
                    "run_command are blocked."
                ),
                (
                    "Pre-existing dirty files: "
                    + (
                        ", ".join(
                            preexisting
                        )
                        if preexisting
                        else "(none)"
                    )
                ),
            ]
        )
