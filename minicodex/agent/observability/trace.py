"""Structured event tracing for MiniCodex."""

from __future__ import annotations

from collections import Counter
from dataclasses import (
    asdict,
    dataclass,
)
from enum import Enum
from pathlib import Path
from typing import Any
from datetime import (
    datetime,
    timezone,
)
import json
import uuid
from .redaction import redact


# =============================================================
# Trace Event Types
# =============================================================


class TraceEventType(
    str,
    Enum,
):

    TASK_STARTED = "task_started"
    TASK_FINISHED = "task_finished"
    TASK_FAILED = "task_failed"

    LLM_STARTED = "llm_started"
    LLM_FINISHED = "llm_finished"
    LLM_FAILED = "llm_failed"

    TOOL_REQUESTED = "tool_requested"
    TOOL_FINISHED = "tool_finished"

    SAFETY_DECISION = "safety_decision"

    EDIT_APPLIED = "edit_applied"

    VALIDATION_RUN = "validation_run"

    ROLLBACK_STARTED = "rollback_started"
    ROLLBACK_FINISHED = "rollback_finished"

    REPLAN_STARTED = "replan_started"
    REPLAN_FINISHED = "replan_finished"

    PLAN_STEP_COMPLETED = "plan_step_completed"


# =============================================================
# Trace Event
# =============================================================


@dataclass(frozen=True)
class TraceEvent:

    sequence: int

    event_type: TraceEventType

    timestamp: str

    task_id: str | None

    data: dict[
        str,
        Any,
    ]

    def to_dict(
        self,
    ) -> dict:

        return {
            "sequence": (
                self.sequence
            ),
            "event_type": (
                self.event_type.value
            ),
            "timestamp": (
                self.timestamp
            ),
            "task_id": (
                self.task_id
            ),
            "data": (
                _json_safe(
                    self.data
                )
            ),
        }


# =============================================================
# Trace Summary
# =============================================================


@dataclass(frozen=True)
class TraceSummary:

    task_id: str | None

    total_events: int

    event_counts: dict[
        str,
        int,
    ]

    llm_calls: int

    tool_calls: int

    edits: int

    validation_runs: int

    rollbacks: int

    replans: int

    safety_blocks: int

    safety_cautions: int

    def to_dict(
        self,
    ) -> dict:

        return asdict(
            self
        )


# =============================================================
# Trace Recorder
# =============================================================


class TraceRecorder:
    """
    Append-only structured event recorder.

    Important design rule:

        Trace observes execution.

    It does NOT:

        - decide policy
        - execute tools
        - decide validation
        - decide rollback
        - decide completion

    Therefore a tracing failure must never change Agent
    behaviour.
    """

    def __init__(
        self,
        *,
        max_events: int = 5000,
    ):

        self.max_events = max(
            1,
            int(
                max_events
            ),
        )

        self.events: list[
            TraceEvent
        ] = []

        self.task_id: (
            str
            | None
        ) = None

        self._sequence = 0

    # =========================================================
    # Reset
    # =========================================================

    def reset(
        self,
    ) -> None:

        self.events.clear()

        self.task_id = None

        self._sequence = 0

    # =========================================================
    # Start Task
    # =========================================================

    def start_task(
        self,
        *,
        prompt: str,
    ) -> str:

        self.reset()

        self.task_id = (
            uuid.uuid4()
            .hex
        )

        self.emit(
            TraceEventType.TASK_STARTED,
            {
                "prompt": (
                    prompt
                ),
            },
        )

        return (
            self.task_id
        )

    # =========================================================
    # Emit
    # =========================================================

    def emit(
        self,
        event_type: (
            TraceEventType
            | str
        ),
        data: (
            dict
            | None
        ) = None,
    ) -> TraceEvent:

        if not isinstance(
            event_type,
            TraceEventType,
        ):

            event_type = (
                TraceEventType(
                    event_type
                )
            )

        self._sequence += 1

        event = (
            TraceEvent(
                sequence=(
                    self._sequence
                ),
                event_type=(
                    event_type
                ),
                timestamp=(
                    datetime.now(
                        timezone.utc
                    )
                    .isoformat()
                ),
                task_id=(
                    self.task_id
                ),
                data=redact(_json_safe(data or {})),
            )
        )

        self.events.append(
            event
        )

        if (
            len(
                self.events
            )
            > self.max_events
        ):

            self.events = (
                self.events[
                    -self.max_events:
                ]
            )

        return event

    # =========================================================
    # Summary
    # =========================================================

    def summary(
        self,
    ) -> TraceSummary:

        counts = Counter(
            event.event_type.value
            for event
            in self.events
        )

        safety_blocks = 0

        safety_cautions = 0

        for event in (
            self.events
        ):

            if (
                event.event_type
                != (
                    TraceEventType
                    .SAFETY_DECISION
                )
            ):

                continue

            level = (
                event.data
                .get(
                    "level"
                )
            )

            if (
                level
                == "blocked"
            ):

                safety_blocks += 1

            elif (
                level
                == "caution"
            ):

                safety_cautions += 1

        return TraceSummary(
            task_id=(
                self.task_id
            ),
            total_events=(
                len(
                    self.events
                )
            ),
            event_counts=dict(
                counts
            ),
            llm_calls=(
                counts[
                    TraceEventType
                    .LLM_FINISHED
                    .value
                ]
            ),
            tool_calls=(
                counts[
                    TraceEventType
                    .TOOL_FINISHED
                    .value
                ]
            ),
            edits=(
                counts[
                    TraceEventType
                    .EDIT_APPLIED
                    .value
                ]
            ),
            validation_runs=(
                counts[
                    TraceEventType
                    .VALIDATION_RUN
                    .value
                ]
            ),
            rollbacks=(
                counts[
                    TraceEventType
                    .ROLLBACK_FINISHED
                    .value
                ]
            ),
            replans=(
                counts[
                    TraceEventType
                    .REPLAN_FINISHED
                    .value
                ]
            ),
            safety_blocks=(
                safety_blocks
            ),
            safety_cautions=(
                safety_cautions
            ),
        )

    # =========================================================
    # JSON
    # =========================================================

    def to_dicts(
        self,
    ) -> list[
        dict
    ]:

        return [
            event.to_dict()
            for event
            in self.events
        ]

    # =========================================================
    # Save JSONL
    # =========================================================

    def save_jsonl(
        self,
        path,
    ) -> None:

        target = (
            Path(
                path
            )
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        lines = [
            json.dumps(
                event.to_dict(),
                ensure_ascii=False,
            )
            for event
            in self.events
        ]

        text = "\n".join(
            lines
        )

        if text:

            text += "\n"

        target.write_text(
            text,
            encoding="utf-8",
        )


# =============================================================
# JSON-Safe Conversion
# =============================================================


def _json_safe(
    value,
):

    if (
        value
        is None
        or isinstance(
            value,
            (
                str,
                int,
                float,
                bool,
            ),
        )
    ):

        return value

    if isinstance(
        value,
        Enum,
    ):

        return (
            value.value
        )

    if isinstance(
        value,
        Path,
    ):

        return str(
            value
        )

    if isinstance(
        value,
        dict,
    ):

        return {
            str(
                key
            ): _json_safe(
                item
            )
            for (
                key,
                item,
            )
            in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):

        return [
            _json_safe(
                item
            )
            for item
            in value
        ]

    if hasattr(
        value,
        "to_dict",
    ):

        try:

            return _json_safe(
                value.to_dict()
            )

        except Exception:

            pass

    return str(
        value
    )
