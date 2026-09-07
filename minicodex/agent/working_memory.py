"""Structured task-local working memory for MiniCodex."""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)
from enum import Enum
from hashlib import sha1
from typing import Any


# =============================================================
# Memory Kinds
# =============================================================


class MemoryKind(
    str,
    Enum,
):

    FILE = "file"

    SEARCH = "search"

    VALIDATION = "validation"

    COMMAND = "command"

    PLAN = "plan"

    SAFETY = "safety"

    GIT = "git"

    FAILURE = "failure"

    GENERAL = "general"


# =============================================================
# Working Memory Entry
# =============================================================


@dataclass(frozen=True)
class WorkingMemoryEntry:
    """
    One CURRENT task-local fact.

    `key` is its logical identity.

    Upserting the same key replaces the previous value instead
    of accumulating stale copies.
    """

    key: str

    kind: MemoryKind

    value: str

    source_tool: str | None

    sequence: int

    path: str | None = None

    revision: int | None = None

    metadata: dict[
        str,
        Any,
    ] = field(
        default_factory=dict
    )

    def to_dict(
        self,
    ) -> dict:

        return {
            "key": (
                self.key
            ),
            "kind": (
                self.kind.value
            ),
            "value": (
                self.value
            ),
            "source_tool": (
                self.source_tool
            ),
            "sequence": (
                self.sequence
            ),
            "path": (
                self.path
            ),
            "revision": (
                self.revision
            ),
            "metadata": dict(
                self.metadata
            ),
        }


# =============================================================
# Working Memory
# =============================================================


class WorkingMemory:
    """
    Structured, mutable, task-local Agent memory.

    WorkingMemory is NOT a source of truth.

    Real tools / filesystem / Git / validation remain the
    authoritative sources.

    WorkingMemory acts as a compact cache of the latest known
    task state.

    Important difference from WorkingSummary:

        WorkingSummary:
            append-ish recent execution history

        WorkingMemory:
            keyed latest-known state

    Example:

        read app.py
            ↓
        memory:
            file:app.py:observation

        edit app.py
            ↓
        old app.py observation becomes stale
            ↓
        invalidate old file memory
            ↓
        memory:
            file:app.py:edit
    """

    EDIT_TOOLS = {
        "patch_file",
        "replace_lines",
        "replace_symbol",
        "write_file",
    }

    def __init__(
        self,
        *,
        max_entries: int = 24,
        max_render_entries: int = 16,
    ):

        self.max_entries = max(
            1,
            int(
                max_entries
            ),
        )

        self.max_render_entries = max(
            1,
            int(
                max_render_entries
            ),
        )

        self.entries: dict[
            str,
            WorkingMemoryEntry,
        ] = {}

        self._sequence = 0

    # =========================================================
    # Reset
    # =========================================================

    def reset(
        self,
    ) -> None:

        self.entries.clear()

        self._sequence = 0

    # =========================================================
    # Length
    # =========================================================

    def __len__(
        self,
    ) -> int:

        return len(
            self.entries
        )

    # =========================================================
    # Get
    # =========================================================

    def get(
        self,
        key: str,
    ) -> WorkingMemoryEntry | None:

        return (
            self.entries
            .get(
                key
            )
        )

    # =========================================================
    # Upsert
    # =========================================================

    def upsert(
        self,
        *,
        key: str,
        kind: MemoryKind,
        value: str,
        source_tool: str | None = None,
        path: str | None = None,
        revision: int | None = None,
        metadata: dict | None = None,
    ) -> WorkingMemoryEntry | None:

        normalized_key = (
            str(
                key
            )
            .strip()
        )

        normalized_value = (
            str(
                value
            )
            .strip()
        )

        if (
            not normalized_key
            or not normalized_value
        ):

            return None

        self._sequence += 1

        entry = (
            WorkingMemoryEntry(
                key=(
                    normalized_key
                ),
                kind=(
                    kind
                ),
                value=(
                    normalized_value
                ),
                source_tool=(
                    source_tool
                ),
                sequence=(
                    self._sequence
                ),
                path=(
                    self._normalize_text(
                        path
                    )
                ),
                revision=(
                    revision
                ),
                metadata=dict(
                    metadata
                    or {}
                ),
            )
        )

        self.entries[
            normalized_key
        ] = entry

        self._enforce_limit()

        return entry

    # =========================================================
    # Remove
    # =========================================================

    def remove(
        self,
        key: str,
    ) -> None:

        self.entries.pop(
            key,
            None,
        )

    # =========================================================
    # Invalidate File Knowledge
    # =========================================================

    def invalidate_path(
        self,
        path: str,
    ) -> int:
        """
        Remove cached knowledge tied to a physical file.

        This is used after a successful edit because previous
        observations of that file may now be stale.

        Returns the number of entries removed.
        """

        normalized = (
            self._normalize_text(
                path
            )
        )

        if not normalized:

            return 0

        stale_keys = [
            key
            for (
                key,
                entry,
            )
            in self.entries.items()
            if (
                entry.path
                == normalized
            )
        ]

        for key in (
            stale_keys
        ):

            self.entries.pop(
                key,
                None,
            )

        return len(
            stale_keys
        )

    # =========================================================
    # Tool Result Observation
    # =========================================================

    def record_tool_result(
        self,
        *,
        tool_name: str,
        arguments: dict,
        result,
    ) -> None:

        if not isinstance(
            arguments,
            dict,
        ):

            arguments = {}

        data = getattr(
            result,
            "data",
            None,
        )

        if not isinstance(
            data,
            dict,
        ):

            data = {}

        path = (
            self._normalize_text(
                arguments.get(
                    "path"
                )
            )
            or self._normalize_text(
                data.get(
                    "path"
                )
            )
        )

        # =====================================================
        # Read File
        # =====================================================

        if (
            tool_name
            == "read_file"
            and result.success
            and path
        ):

            start_line = (
                data.get(
                    "start_line"
                )
            )

            end_line = (
                data.get(
                    "end_line"
                )
            )

            total_lines = (
                data.get(
                    "total_lines"
                )
            )

            has_more = (
                data.get(
                    "has_more"
                )
            )

            description = (
                f"Observed {path}"
            )

            if (
                start_line
                is not None
                and end_line
                is not None
            ):

                description += (
                    f" lines "
                    f"{start_line}-"
                    f"{end_line}"
                )

            if (
                total_lines
                is not None
            ):

                description += (
                    f" of "
                    f"{total_lines}"
                )

            description += "."

            if (
                has_more
                is True
            ):

                description += (
                    " More lines remain unread."
                )

            self.upsert(
                key=(
                    f"file:"
                    f"{path}:"
                    "observation"
                ),
                kind=(
                    MemoryKind.FILE
                ),
                value=(
                    description
                ),
                source_tool=(
                    tool_name
                ),
                path=(
                    path
                ),
                metadata={
                    "start_line": (
                        start_line
                    ),
                    "end_line": (
                        end_line
                    ),
                    "total_lines": (
                        total_lines
                    ),
                    "has_more": (
                        has_more
                    ),
                },
            )

        # =====================================================
        # Search Code
        # =====================================================

        elif (
            tool_name
            == "search_code"
            and result.success
        ):

            query = (
                self._normalize_text(
                    arguments.get(
                        "query"
                    )
                )
            )

            if query:

                self.upsert(
                    key=(
                        "search_code:"
                        f"{query}"
                    ),
                    kind=(
                        MemoryKind.SEARCH
                    ),
                    value=(
                        "Project text search "
                        f"completed for: {query}."
                    ),
                    source_tool=(
                        tool_name
                    ),
                    metadata={
                        "query": (
                            query
                        ),
                    },
                )

        # =====================================================
        # Search Symbol
        # =====================================================

        elif (
            tool_name
            == "search_symbol"
            and result.success
        ):

            query = (
                self._normalize_text(
                    arguments.get(
                        "query"
                    )
                )
                or self._normalize_text(
                    arguments.get(
                        "name"
                    )
                )
            )

            if query:

                self.upsert(
                    key=(
                        "search_symbol:"
                        f"{query}"
                    ),
                    kind=(
                        MemoryKind.SEARCH
                    ),
                    value=(
                        "Symbol search "
                        f"completed for: {query}."
                    ),
                    source_tool=(
                        tool_name
                    ),
                    metadata={
                        "query": (
                            query
                        ),
                    },
                )

        # =====================================================
        # Successful Edit
        # =====================================================

        elif (
            tool_name
            in self.EDIT_TOOLS
            and result.success
            and path
        ):

            # Any earlier read / state knowledge about this file
            # may now be stale.
            self.invalidate_path(
                path
            )

            revision_value = (
                data.get(
                    "checkpoint_revision"
                )
            )

            try:

                revision = (
                    int(
                        revision_value
                    )
                    if (
                        revision_value
                        is not None
                    )
                    else None
                )

            except (
                TypeError,
                ValueError,
            ):

                revision = None

            value = (
                "Latest known successful "
                f"Agent edit changed {path}"
            )

            if (
                revision
                is not None
            ):

                value += (
                    f" for edit revision "
                    f"{revision}"
                )

            value += "."

            if (
                data.get(
                    "safety_degraded"
                )
                is True
            ):

                value += (
                    " Checkpoint safety was degraded."
                )

            self.upsert(
                key=(
                    f"file:"
                    f"{path}:"
                    "edit"
                ),
                kind=(
                    MemoryKind.FILE
                ),
                value=(
                    value
                ),
                source_tool=(
                    tool_name
                ),
                path=(
                    path
                ),
                revision=(
                    revision
                ),
                metadata={
                    "checkpoint_id": (
                        data.get(
                            "checkpoint_id"
                        )
                    ),
                    "checkpoint_sealed": (
                        data.get(
                            "checkpoint_sealed"
                        )
                    ),
                    "safety_degraded": (
                        data.get(
                            "safety_degraded"
                        )
                    ),
                },
            )

        # =====================================================
        # Validation
        # =====================================================

        elif tool_name == "validate_static_web":
            outcome = self._normalize_text(
                data.get("outcome")
            ) or "inconclusive"
            validation_path = path or "unknown"
            self.upsert(
                key=f"validation:acceptance:{validation_path}",
                kind=MemoryKind.VALIDATION,
                value=(
                    f"Latest static web acceptance validation "
                    f"for {validation_path}: {outcome}."
                ),
                source_tool=tool_name,
                path=path or None,
                metadata=dict(data),
            )

        elif (
            tool_name
            == "run_tests"
        ):

            purpose = (
                self._normalize_text(
                    arguments.get(
                        "purpose"
                    )
                )
                or self._normalize_text(
                    data.get(
                        "purpose"
                    )
                )
                or "regression"
            )

            test_path = (
                path
                or "."
            )

            passed = (
                self._safe_int(
                    data.get(
                        "passed"
                    )
                )
            )

            failed = (
                self._safe_int(
                    data.get(
                        "failed"
                    )
                )
            )

            errors = (
                self._safe_int(
                    data.get(
                        "errors"
                    )
                )
            )

            tests_passed = (
                data.get(
                    "tests_passed"
                )
            )

            if not result.success:

                state = (
                    "execution failed"
                )

            elif (
                tests_passed
                is True
            ):

                state = (
                    "passed"
                )

            elif (
                tests_passed
                is False
            ):

                state = (
                    "failed"
                )

            else:

                state = (
                    "inconclusive"
                )

            value = (
                f"Latest {purpose} validation "
                f"for {test_path}: "
                f"{state}; "
                f"{passed} passed, "
                f"{failed} failed, "
                f"{errors} errors."
            )

            self.upsert(
                key=(
                    "validation:"
                    f"{purpose}:"
                    f"{test_path}"
                ),
                kind=(
                    MemoryKind.VALIDATION
                ),
                value=(
                    value
                ),
                source_tool=(
                    tool_name
                ),
                path=(
                    test_path
                    if (
                        test_path
                        != "."
                    )
                    else None
                ),
                metadata={
                    "purpose": (
                        purpose
                    ),
                    "passed": (
                        passed
                    ),
                    "failed": (
                        failed
                    ),
                    "errors": (
                        errors
                    ),
                    "tests_passed": (
                        tests_passed
                    ),
                },
            )

        # =====================================================
        # Dependency Installation
        # =====================================================

        elif tool_name == "install_python_package":
            package = self._normalize_text(
                arguments.get("package")
            )
            import_name = self._normalize_text(
                arguments.get("import_name")
            )

            if package:
                if result.success:
                    state = (
                        "already available"
                        if data.get("already_available")
                        else "installed and import-verified"
                    )
                else:
                    state = "installation failed"

                self.upsert(
                    key=f"dependency:{package}",
                    kind=MemoryKind.GENERAL,
                    value=(
                        f"Python dependency {package} "
                        f"({import_name or 'unknown import'}) "
                        f"is {state}."
                    ),
                    source_tool=tool_name,
                    metadata={
                        "package": package,
                        "import_name": import_name,
                        "installed": data.get("installed"),
                        "import_verified": data.get(
                            "import_verified"
                        ),
                    },
                )

        # =====================================================
        # Run Command
        # =====================================================

        elif (
            tool_name
            == "run_command"
        ):

            command = (
                self._normalize_text(
                    arguments.get(
                        "command"
                    )
                )
            )

            if command:

                command_succeeded = (
                    data.get(
                        "command_succeeded"
                    )
                )

                if (
                    result.success
                    and command_succeeded
                    is True
                ):

                    state = (
                        "succeeded"
                    )

                elif (
                    result.success
                    and command_succeeded
                    is False
                ):

                    state = (
                        "completed unsuccessfully"
                    )

                else:

                    state = (
                        "failed"
                    )

                digest = (
                    sha1(
                        command.encode(
                            "utf-8"
                        )
                    )
                    .hexdigest()[
                        :12
                    ]
                )

                self.upsert(
                    key=(
                        "command:"
                        f"{digest}"
                    ),
                    kind=(
                        MemoryKind.COMMAND
                    ),
                    value=(
                        f"Command {state}: "
                        f"{command}."
                    ),
                    source_tool=(
                        tool_name
                    ),
                    metadata={
                        "command": (
                            command
                        ),
                        "command_succeeded": (
                            command_succeeded
                        ),
                    },
                )

        # =====================================================
        # Git Status
        # =====================================================

        elif (
            tool_name
            == "git_status"
            and result.success
        ):

            current = (
                data.get(
                    "current"
                )
            )

            if isinstance(
                current,
                dict,
            ):

                dirty = (
                    current.get(
                        "dirty"
                    )
                )

                changed = (
                    current.get(
                        "changed_files"
                    )
                    or []
                )

                self.upsert(
                    key=(
                        "git:current"
                    ),
                    kind=(
                        MemoryKind.GIT
                    ),
                    value=(
                        "Latest observed Git state: "
                        f"dirty={dirty}; "
                        "changed files="
                        + (
                            ", ".join(
                                str(
                                    item
                                )
                                for item
                                in changed
                            )
                            if changed
                            else "(none)"
                        )
                        + "."
                    ),
                    source_tool=(
                        tool_name
                    ),
                    metadata={
                        "dirty": (
                            dirty
                        ),
                        "changed_files": (
                            list(
                                changed
                            )
                        ),
                    },
                )

        # =====================================================
        # Git Diff
        # =====================================================

        elif (
            tool_name
            == "git_diff"
            and result.success
        ):

            diff_path = (
                path
                or "(all changes)"
            )

            staged = bool(
                arguments.get(
                    "staged",
                    False,
                )
            )

            self.upsert(
                key=(
                    "git_diff:"
                    f"{diff_path}:"
                    f"{staged}"
                ),
                kind=(
                    MemoryKind.GIT
                ),
                value=(
                    "Git diff inspected for "
                    f"{diff_path}; "
                    f"staged={staged}."
                ),
                source_tool=(
                    tool_name
                ),
                path=(
                    path
                ),
                metadata={
                    "staged": (
                        staged
                    ),
                },
            )

        # =====================================================
        # Complete Plan Step
        # =====================================================

        elif (
            tool_name
            == "complete_plan_step"
            and data.get(
                "completed"
            )
        ):

            step_id = (
                data.get(
                    "step_id"
                )
            )

            description = (
                self._normalize_text(
                    data.get(
                        "step_description"
                    )
                )
            )

            self.upsert(
                key=(
                    "plan:"
                    f"step:{step_id}"
                ),
                kind=(
                    MemoryKind.PLAN
                ),
                value=(
                    f"Plan step {step_id} "
                    "completed"
                    + (
                        f": {description}."
                        if description
                        else "."
                    )
                ),
                source_tool=(
                    tool_name
                ),
                metadata={
                    "step_id": (
                        step_id
                    ),
                },
            )

        # =====================================================
        # Replan
        # =====================================================

        elif (
            tool_name
            == "replan"
            and data.get(
                "replanned"
            )
        ):

            reason = (
                self._normalize_text(
                    data.get(
                        "reason"
                    )
                )
            )

            self.upsert(
                key=(
                    "plan:latest_replan"
                ),
                kind=(
                    MemoryKind.PLAN
                ),
                value=(
                    "Implementation plan "
                    "was revised."
                    + (
                        f" Reason: {reason}"
                        if reason
                        else ""
                    )
                ),
                source_tool=(
                    tool_name
                ),
                metadata={
                    "reason": (
                        reason
                    ),
                },
            )

        # =====================================================
        # Generic Failure
        # =====================================================

        if not result.success:

            target = (
                path
                or self._normalize_text(
                    arguments.get(
                        "query"
                    )
                )
                or self._normalize_text(
                    arguments.get(
                        "command"
                    )
                )
                or "(none)"
            )

            error = (
                self._normalize_text(
                    getattr(
                        result,
                        "error",
                        None,
                    )
                )
                or "unknown failure"
            )

            self.upsert(
                key=(
                    "failure:"
                    f"{tool_name}:"
                    f"{target}"
                ),
                kind=(
                    MemoryKind.FAILURE
                ),
                value=(
                    f"Latest failure for "
                    f"{tool_name} "
                    f"on {target}: "
                    f"{error}"
                ),
                source_tool=(
                    tool_name
                ),
                path=(
                    path
                ),
                metadata={
                    "failure_type": (
                        data.get(
                            "failure_type"
                        )
                    ),
                },
            )

        # =====================================================
        # Safety Risk
        #
        # Record this AFTER file invalidation so a caution entry
        # caused by editing pre-existing user work is preserved.
        # =====================================================

        self._record_safety(
            tool_name=(
                tool_name
            ),
            arguments=(
                arguments
            ),
            data=(
                data
            ),
            path=(
                path
            ),
        )

    # =========================================================
    # Safety Memory
    # =========================================================

    def _record_safety(
        self,
        *,
        tool_name: str,
        arguments: dict,
        data: dict,
        path: str | None,
    ) -> None:

        safety = (
            data.get(
                "safety"
            )
        )

        if not isinstance(
            safety,
            dict,
        ):

            return

        level = (
            self._normalize_text(
                safety.get(
                    "level"
                )
            )
        )

        if (
            level
            not in {
                "caution",
                "blocked",
            }
        ):

            return

        rule = (
            self._normalize_text(
                safety.get(
                    "rule"
                )
            )
            or "unknown"
        )

        reason = (
            self._normalize_text(
                safety.get(
                    "reason"
                )
            )
            or "No reason supplied."
        )

        target = (
            path
            or self._normalize_text(
                arguments.get(
                    "command"
                )
            )
            or tool_name
        )

        target_digest = (
            sha1(
                target.encode(
                    "utf-8"
                )
            )
            .hexdigest()[
                :12
            ]
        )

        self.upsert(
            key=(
                "safety:"
                f"{tool_name}:"
                f"{target_digest}"
            ),
            kind=(
                MemoryKind.SAFETY
            ),
            value=(
                f"Safety {level}: "
                f"{tool_name}; "
                f"rule={rule}; "
                f"{reason}"
            ),
            source_tool=(
                tool_name
            ),
            path=(
                path
            ),
            metadata={
                "level": (
                    level
                ),
                "rule": (
                    rule
                ),
            },
        )

    # =========================================================
    # Render
    # =========================================================

    def render(
        self,
        *,
        max_entries: int | None = None,
    ) -> str:

        if not self.entries:

            return (
                "No structured working-memory "
                "state is currently available."
            )

        limit = (
            self.max_render_entries
            if (
                max_entries
                is None
            )
            else max(
                1,
                int(
                    max_entries
                ),
            )
        )

        ordered = sorted(
            self.entries.values(),
            key=lambda entry: (
                entry.sequence
            ),
        )

        selected = (
            ordered[
                -limit:
            ]
        )

        return "\n".join(
            (
                f"- [{entry.kind.value}] "
                f"{entry.value}"
            )
            for entry
            in selected
        )

    # =========================================================
    # Dict
    # =========================================================

    def to_dict(
        self,
    ) -> dict:

        ordered = sorted(
            self.entries.values(),
            key=lambda entry: (
                entry.sequence
            ),
        )

        return {
            "count": (
                len(
                    ordered
                )
            ),
            "entries": [
                entry.to_dict()
                for entry
                in ordered
            ],
        }

    # =========================================================
    # Enforce Bound
    # =========================================================

    def _enforce_limit(
        self,
    ) -> None:

        overflow = (
            len(
                self.entries
            )
            - self.max_entries
        )

        if (
            overflow
            <= 0
        ):

            return

        oldest = sorted(
            self.entries.values(),
            key=lambda entry: (
                entry.sequence
            ),
        )[
            :overflow
        ]

        for entry in (
            oldest
        ):

            self.entries.pop(
                entry.key,
                None,
            )

    # =========================================================
    # Helpers
    # =========================================================

    @staticmethod
    def _normalize_text(
        value,
    ) -> str:

        if (
            value
            is None
        ):

            return ""

        return (
            str(
                value
            )
            .strip()
        )

    @staticmethod
    def _safe_int(
        value,
    ) -> int:

        try:

            return int(
                value
                or 0
            )

        except (
            TypeError,
            ValueError,
        ):

            return 0
