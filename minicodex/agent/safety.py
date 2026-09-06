"""Deterministic safety and permission policy for MiniCodex."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re


# =============================================================
# Safety Levels
# =============================================================


class SafetyLevel(str, Enum):

    SAFE = "safe"

    CAUTION = "caution"

    BLOCKED = "blocked"


# =============================================================
# Safety Decision
# =============================================================


@dataclass(frozen=True)
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

    Stage 12 is NOT a full security sandbox.

    It protects against deterministic, recognizable unsafe
    operations at the tool-call boundary.

    Full process isolation belongs to the later Sandbox stage.
    """

    EDIT_TOOL_NAMES = {
        "patch_file",
        "replace_lines",
        "replace_symbol",
        "write_file",
    }

    # =========================================================
    # Always Blocked Commands
    # =========================================================

    BLOCKED_COMMAND_PATTERNS = (
        (
            "destructive_rm",
            re.compile(
                r"(^|[;&|]\s*)rm(?:\s|$)",
                re.IGNORECASE,
            ),
        ),
        (
            "privilege_escalation",
            re.compile(
                r"(^|[;&|]\s*)sudo(?:\s|$)",
                re.IGNORECASE,
            ),
        ),
        (
            "system_shutdown",
            re.compile(
                r"\b("
                r"shutdown|"
                r"reboot|"
                r"poweroff|"
                r"halt"
                r")\b",
                re.IGNORECASE,
            ),
        ),
        (
            "disk_operation",
            re.compile(
                r"\b("
                r"mkfs(?:\.\w+)?|"
                r"fdisk|"
                r"parted"
                r")\b",
                re.IGNORECASE,
            ),
        ),
        (
            "raw_disk_write",
            re.compile(
                r"\bdd\b.*\bof\s*=",
                re.IGNORECASE,
            ),
        ),
        (
            "ownership_change",
            re.compile(
                r"(^|[;&|]\s*)("
                r"chmod|"
                r"chown|"
                r"chgrp"
                r")(?:\s|$)",
                re.IGNORECASE,
            ),
        ),
        (
            "process_termination",
            re.compile(
                r"(^|[;&|]\s*)("
                r"kill|"
                r"killall|"
                r"pkill"
                r")(?:\s|$)",
                re.IGNORECASE,
            ),
        ),
        (
            "direct_file_mutation",
            re.compile(
                r"(^|[;&|]\s*)("
                r"mv|"
                r"cp|"
                r"touch|"
                r"truncate|"
                r"mkdir|"
                r"rmdir|"
                r"ln"
                r")(?:\s|$)",
                re.IGNORECASE,
            ),
        ),
        (
            "sed_in_place",
            re.compile(
                r"\bsed\s+[^;&|]*"
                r"(?:-i|--in-place)",
                re.IGNORECASE,
            ),
        ),
        (
            "perl_in_place",
            re.compile(
                r"\bperl\s+[^;&|]*"
                r"-[A-Za-z]*i[A-Za-z]*",
                re.IGNORECASE,
            ),
        ),
        (
            "tee_write",
            re.compile(
                r"(^|[|;&]\s*)tee(?:\s|$)",
                re.IGNORECASE,
            ),
        ),
    )

    # =========================================================
    # Git Mutation
    # =========================================================

    GIT_MUTATION_PATTERN = re.compile(
        r"\bgit\s+"
        r"(?:"
        r"-[A-Za-z0-9._=-]+\s+"
        r")*"
        r"("
        r"add|"
        r"commit|"
        r"reset|"
        r"clean|"
        r"checkout|"
        r"restore|"
        r"stash|"
        r"switch|"
        r"merge|"
        r"rebase|"
        r"cherry-pick|"
        r"revert|"
        r"push|"
        r"pull"
        r")\b",
        re.IGNORECASE,
    )

    GIT_BRANCH_MUTATION_PATTERN = re.compile(
        r"\bgit\s+branch\s+"
        r"(?:-[dDmM]|--delete|--move)\b",
        re.IGNORECASE,
    )

    GIT_TAG_MUTATION_PATTERN = re.compile(
        r"\bgit\s+tag\s+"
        r"(?:-d|--delete)\b",
        re.IGNORECASE,
    )

    # =========================================================
    # Caution Commands
    # =========================================================

    NETWORK_PATTERN = re.compile(
        r"(^|[;&|]\s*)("
        r"curl|"
        r"wget"
        r")(?:\s|$)",
        re.IGNORECASE,
    )

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
    # Main Assessment
    # =========================================================

    def assess(
        self,
        tool_name: str,
        arguments: dict,
    ) -> SafetyDecision:

        # =====================================================
        # Shell Command
        # =====================================================

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

        # =====================================================
        # Filesystem Edit
        # =====================================================

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

        # =====================================================
        # Other Tools
        # =====================================================

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

        # CheckpointExecutor remains responsible for the
        # explicit-path precondition itself.
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
                    "The downstream checkpoint "
                    "precondition will validate it."
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
                    "Direct modification of "
                    "Git internal metadata is "
                    "not allowed."
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
        # Current Merge Conflict
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
                    "The target file currently has "
                    "a Git conflict and requires "
                    "extra care."
                ),
                rule=(
                    "git_conflict"
                ),
                tool_name=tool_name,
                path=normalized,
            )

        # =====================================================
        # Normal Workspace Edit
        # =====================================================

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
                    "No command was available for "
                    "classification. Downstream "
                    "argument validation will "
                    "handle the call."
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

        # =====================================================
        # Empty Command
        # =====================================================

        if not command:

            return SafetyDecision(
                level=(
                    SafetyLevel.SAFE
                ),
                allowed=True,
                reason=(
                    "Empty command contains no "
                    "recognized destructive action."
                ),
                rule=(
                    "empty_command"
                ),
                tool_name=tool_name,
                command=command,
            )

        # =====================================================
        # Destructive Git Mutation
        # =====================================================

        git_match = (
            self.GIT_MUTATION_PATTERN
            .search(
                command
            )
        )

        if git_match:

            return SafetyDecision(
                level=(
                    SafetyLevel.BLOCKED
                ),
                allowed=False,
                reason=(
                    "Mutating Git operations are "
                    "blocked through run_command. "
                    "Stage 11 Git access is "
                    "observational only."
                ),
                rule=(
                    "git_mutation"
                ),
                tool_name=tool_name,
                command=command,
            )

        if (
            self.GIT_BRANCH_MUTATION_PATTERN
            .search(
                command
            )
            or (
                self.GIT_TAG_MUTATION_PATTERN
                .search(
                    command
                )
            )
        ):

            return SafetyDecision(
                level=(
                    SafetyLevel.BLOCKED
                ),
                allowed=False,
                reason=(
                    "Destructive Git reference "
                    "mutation is blocked."
                ),
                rule=(
                    "git_reference_mutation"
                ),
                tool_name=tool_name,
                command=command,
            )

        # =====================================================
        # Direct Shell Redirection
        #
        # This can bypass CheckpointingToolExecutor.
        # Permit redirects only when they clearly target
        # /dev/null.
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
                    "write files outside the edit/"
                    "checkpoint pipeline."
                ),
                rule=(
                    "checkpoint_bypass_redirection"
                ),
                tool_name=tool_name,
                command=command,
            )

        # =====================================================
        # Other Explicitly Blocked Patterns
        # =====================================================

        for (
            rule,
            pattern,
        ) in self.BLOCKED_COMMAND_PATTERNS:

            if pattern.search(
                command
            ):

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

        # =====================================================
        # Network
        # =====================================================

        if (
            self.NETWORK_PATTERN
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
        # Package Installation
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

        # =====================================================
        # Default Command
        # =====================================================

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
    # Unsafe Redirection
    # =========================================================

    @staticmethod
    def _contains_unsafe_redirection(
        command: str,
    ) -> bool:

        # Find shell output redirections:
        #
        #   > file
        #   >> file
        #   2> file
        #
        # Input redirection (<) is not considered a write.
        matches = re.finditer(
            r"(?:\d*)>{1,2}\s*"
            r"([^\s;&|]+)",
            command,
        )

        for match in matches:

            target = (
                match
                .group(
                    1
                )
                .strip(
                    "\"'"
                )
            )

            if (
                target
                != "/dev/null"
            ):

                return True

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
    # Path Normalization
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
    # Render Current Policy
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