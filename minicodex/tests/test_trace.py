import json

from ..agent.observability import (
    TraceEventType,
    TraceRecorder,
)


def test_trace_records_ordered_events():

    recorder = (
        TraceRecorder()
    )

    recorder.start_task(
        prompt="Fix code."
    )

    recorder.emit(
        TraceEventType.LLM_STARTED,
        {
            "message_count": 2,
        },
    )

    recorder.emit(
        TraceEventType.LLM_FINISHED,
        {
            "total_tokens": 100,
        },
    )

    assert (
        len(
            recorder.events
        )
        == 3
    )

    assert (
        recorder.events[
            0
        ].sequence
        == 1
    )

    assert (
        recorder.events[
            1
        ].sequence
        == 2
    )

    assert (
        recorder.events[
            2
        ].sequence
        == 3
    )

    assert (
        recorder.events[
            0
        ].event_type
        == (
            TraceEventType
            .TASK_STARTED
        )
    )


def test_new_task_resets_trace():

    recorder = (
        TraceRecorder()
    )

    first_task = (
        recorder.start_task(
            prompt="first"
        )
    )

    recorder.emit(
        TraceEventType.LLM_STARTED,
        {},
    )

    second_task = (
        recorder.start_task(
            prompt="second"
        )
    )

    assert (
        first_task
        != second_task
    )

    assert (
        len(
            recorder.events
        )
        == 1
    )

    assert (
        recorder.events[
            0
        ].sequence
        == 1
    )


def test_trace_summary():

    recorder = (
        TraceRecorder()
    )

    recorder.start_task(
        prompt="Fix."
    )

    recorder.emit(
        TraceEventType.LLM_FINISHED,
        {},
    )

    recorder.emit(
        TraceEventType.TOOL_FINISHED,
        {},
    )

    recorder.emit(
        TraceEventType.EDIT_APPLIED,
        {},
    )

    recorder.emit(
        TraceEventType.VALIDATION_RUN,
        {},
    )

    recorder.emit(
        TraceEventType.SAFETY_DECISION,
        {
            "level": (
                "blocked"
            ),
        },
    )

    summary = (
        recorder.summary()
    )

    assert (
        summary.llm_calls
        == 1
    )

    assert (
        summary.tool_calls
        == 1
    )

    assert (
        summary.edits
        == 1
    )

    assert (
        summary.validation_runs
        == 1
    )

    assert (
        summary.safety_blocks
        == 1
    )


def test_trace_jsonl(
    tmp_path,
):

    recorder = (
        TraceRecorder()
    )

    recorder.start_task(
        prompt="hello"
    )

    recorder.emit(
        TraceEventType.TOOL_FINISHED,
        {
            "tool_name": (
                "read_file"
            ),
            "success": True,
        },
    )

    target = (
        tmp_path
        / "trace.jsonl"
    )

    recorder.save_jsonl(
        target
    )

    lines = (
        target
        .read_text(
            encoding="utf-8"
        )
        .splitlines()
    )

    assert (
        len(
            lines
        )
        == 2
    )

    first = (
        json.loads(
            lines[
                0
            ]
        )
    )

    second = (
        json.loads(
            lines[
                1
            ]
        )
    )

    assert (
        first[
            "event_type"
        ]
        == "task_started"
    )

    assert (
        second[
            "event_type"
        ]
        == "tool_finished"
    )


def test_trace_is_bounded():

    recorder = (
        TraceRecorder(
            max_events=3
        )
    )

    recorder.start_task(
        prompt="test"
    )

    for index in range(
        5
    ):

        recorder.emit(
            TraceEventType.TOOL_FINISHED,
            {
                "index": (
                    index
                ),
            },
        )

    assert (
        len(
            recorder.events
        )
        == 3
    )

    assert (
        recorder.events[
            -1
        ].data[
            "index"
        ]
        == 4
    )