"""Regression tests for terminal tool-batch control decisions."""

from types import SimpleNamespace

from ..agent.orchestration.tool_event_adapter import ToolEventAdapter
from ..agent.reason_codes import ReasonCode
from ..tools.results import ToolResult


def test_global_edit_denial_stops_after_first_rejected_call():
    rejected = ToolResult(
        success=False,
        summary="write_file blocked",
        data={
            "failure_type": "safety_blocked",
            "safety": {"rule": "task_no_edit_constraint"},
        },
        error="当前任务未授权修改仓库。",
    )
    run = SimpleNamespace(
        tool_name="write_file", arguments={"path": "index.html", "content": "ok"},
        result=rejected, preparation_failed=False, restriction=None,
        duplicate_blocked=False,
    )
    runner = SimpleNamespace(run=lambda agent, call: run)
    adapter = ToolEventAdapter(runner)
    events = []
    adapter._emit_event = lambda *args, **kwargs: None
    adapter._emit_normal_progress = lambda *args, **kwargs: None
    adapter._append_observation = lambda *args, **kwargs: None
    adapter._observe = lambda *args, **kwargs: None
    adapter._close = lambda *args, **kwargs: events.append("batch_closed")
    agent = SimpleNamespace(
        execution_metrics=None,
        action_controller=None,
        registry=SimpleNamespace(
            _tools={"write_file": object()},
            capabilities_for=lambda name: frozenset({"code.edit"}),
        ),
        validation_pipeline=SimpleNamespace(state=SimpleNamespace(edit_revision=0)),
        token_metrics=SimpleNamespace(call_count=1),
        plan_orchestrator=SimpleNamespace(record_attempt_failure=lambda step: None),
        working_summary=SimpleNamespace(record_tool_result=lambda **kwargs: None),
        concrete_blockers=[],
    )
    call = SimpleNamespace(
        id="call-1", function=SimpleNamespace(name="write_file", arguments="{}"),
    )

    outcome = adapter.process(
        agent, call, index=0, tool_calls=[call], messages=[],
        current_plan_step=None, runs=[], evidence_items=[], signals=[],
    )

    assert outcome.early_stop == "当前任务未授权修改仓库。"
    assert outcome.reason_code == ReasonCode.BLOCKED
    assert events == ["batch_closed"]
    assert len(outcome.runs) == 1
