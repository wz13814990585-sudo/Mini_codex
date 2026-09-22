"""Deterministic tests for task-scoped human approval coordination."""

from __future__ import annotations

import threading
import time

import pytest

from ..agent.runtime import PreparedToolCall
from ..agent.safety import (
    ApprovalCoordinator,
    InterventionCategory,
    SafetyDecision,
    SafetyLevel,
)


def _decision(rule: str = "dependency_install") -> SafetyDecision:
    return SafetyDecision(
        level=SafetyLevel.CAUTION,
        allowed=True,
        reason="Needs a human decision.",
        rule=rule,
        tool_name="run_command",
        command="curl https://example.test?api_key=secret",
    )


def _wait_for_pending(coordinator: ApprovalCoordinator) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        pending = coordinator.snapshot()["pending"]
        if pending is not None:
            return pending
        time.sleep(0.005)
    pytest.fail("approval request did not become pending")


def _start_request(coordinator: ApprovalCoordinator, *, rule="dependency_install"):
    result = {}
    prepared = PreparedToolCall(
        "run_command",
        {
            "command": "curl https://example.test?api_key=secret",
            "content": "must not be exposed",
        },
    )

    def run():
        decision = _decision(rule)
        result["approved"] = coordinator.intervene(
            decision.intervention, decision, prepared,
        )

    thread = threading.Thread(target=run)
    thread.start()
    return thread, result


def test_allow_once_unblocks_one_redacted_request():
    coordinator = ApprovalCoordinator(timeout_seconds=2)
    coordinator.begin_task()
    trace_events = []
    coordinator.set_event_sink(
        lambda event_type, data: trace_events.append((event_type, data)),
    )
    thread, result = _start_request(coordinator)
    pending = _wait_for_pending(coordinator)

    assert pending["command"].endswith("api_key=[REDACTED]")
    assert "content" not in pending["arguments"]
    coordinator.resolve(pending["request_id"], "allow_once")
    thread.join(timeout=1)

    assert result == {"approved": True}
    snapshot = coordinator.snapshot()
    assert snapshot["pending"] is None
    assert snapshot["allowed_rules"] == []
    assert [event["event_type"] for event in snapshot["audit"]] == [
        "approval_requested", "approval_resolved",
    ]
    assert snapshot["audit"][1]["data"]["decision"] == "allow_once"
    assert [event_type for event_type, _data in trace_events] == [
        "approval_requested", "approval_resolved",
    ]


def test_allow_task_reuses_only_the_same_rule_until_next_task():
    coordinator = ApprovalCoordinator(timeout_seconds=2)
    coordinator.begin_task()
    thread, result = _start_request(coordinator, rule="network_access")
    pending = _wait_for_pending(coordinator)
    coordinator.resolve(pending["request_id"], "allow_task")
    thread.join(timeout=1)
    assert result["approved"] is True

    prepared = PreparedToolCall("run_command", {"command": "curl https://example.test"})
    decision = _decision("network_access")
    assert coordinator.intervene(decision.intervention, decision, prepared) is True
    assert coordinator.snapshot()["allowed_rules"] == ["network_access"]

    coordinator.begin_task()
    assert coordinator.snapshot()["allowed_rules"] == []
    assert coordinator.snapshot()["audit"] == []


def test_reject_and_stale_request_fail_closed():
    coordinator = ApprovalCoordinator(timeout_seconds=2)
    coordinator.begin_task()
    thread, result = _start_request(coordinator)
    pending = _wait_for_pending(coordinator)

    with pytest.raises(ValueError, match="stale"):
        coordinator.resolve("wrong-id", "allow_once")
    coordinator.resolve(pending["request_id"], "reject")
    thread.join(timeout=1)
    assert result == {"approved": False}


def test_hard_denial_never_becomes_approvable():
    coordinator = ApprovalCoordinator(timeout_seconds=0.05)
    decision = SafetyDecision(
        SafetyLevel.BLOCKED, False, "Never allowed.", "workspace_escape", "write_file",
    )
    assert coordinator.intervene(
        InterventionCategory.APPROVAL,
        decision,
        PreparedToolCall("write_file", {"path": "../outside"}),
    ) is False
    assert coordinator.snapshot()["pending"] is None
    assert coordinator.snapshot()["audit"] == []


def test_unanswered_request_times_out_closed():
    coordinator = ApprovalCoordinator(timeout_seconds=0.02)
    coordinator.begin_task()
    assert coordinator.intervene(
        InterventionCategory.APPROVAL,
        _decision(),
        PreparedToolCall("run_command", {"command": "curl https://example.test"}),
    ) is False
    assert coordinator.snapshot()["pending"] is None
    assert coordinator.snapshot()["audit"][-1]["data"]["resolution"] == "timeout"
