from ..agent.progress_policy import NoProgressPolicy
from ..agent.state import AgentPlan, PlanStep
from ..tools.results import ToolResult


def observation(
    summary="same",
    data=None,
):
    return ToolResult(
        success=True,
        summary=summary,
        data=data or {},
    )


def observe(
    policy,
    tool_name,
    arguments,
    result=None,
):
    return policy.observe_tool_result(
        tool_name=tool_name,
        arguments=arguments,
        result=result or observation(),
        step_id=1,
    )


def test_repeated_same_read_reaches_no_progress_limit():
    policy = NoProgressPolicy(max_no_progress_steps=2)
    first = observe(
        policy,
        "read_file",
        {"path": "game.html", "offset": 1, "limit": 50},
    )
    second = observe(
        policy,
        "read_file",
        {"path": "game.html", "offset": 1, "limit": 50},
    )

    assert first.stuck is False
    assert second.stuck is True
    assert second.repeated_observation is True


def test_repeated_search_does_not_count_as_progress():
    policy = NoProgressPolicy(max_no_progress_steps=2)
    observe(
        policy,
        "search_code",
        {"path": ".", "query": "data-row"},
    )
    decision = observe(
        policy,
        "search_code",
        {"path": ".", "query": "data-row"},
    )

    assert decision.stuck is True


def test_unchanged_git_status_does_not_reset_counter():
    policy = NoProgressPolicy(max_no_progress_steps=2)
    result = observation(
        data={"dirty": True, "changed_files": ["game.html"]}
    )
    observe(policy, "git_status", {}, result)
    decision = observe(policy, "git_status", {}, result)

    assert decision.stuck is True
    assert policy.no_progress_count == 2


def test_successful_edit_resets_no_progress():
    policy = NoProgressPolicy(max_no_progress_steps=3)
    observe(policy, "read_file", {"path": "a"})
    observe(policy, "search_code", {"query": "x"})
    decision = observe(
        policy,
        "write_file",
        {"path": "game.html"},
        observation("written"),
    )

    assert decision.meaningful is True
    assert policy.no_progress_count == 0


def test_changed_validation_evidence_resets_no_progress():
    policy = NoProgressPolicy(max_no_progress_steps=3)
    observe(policy, "read_file", {"path": "a"})
    decision = observe(
        policy,
        "validate_static_web",
        {"path": "game.html"},
        observation(data={"outcome": "passed"}),
    )

    assert decision.meaningful is True
    assert policy.no_progress_count == 0


def test_stuck_recovery_restricts_inspection_without_completing_plan():
    policy = NoProgressPolicy(max_no_progress_steps=1)
    plan = AgentPlan(
        goal="game",
        steps=[PlanStep(id=1, description="Inspect game")],
    )
    observe(policy, "read_file", {"path": "game.html"})

    assert policy.restriction_reason("read_file") is not None
    assert policy.restriction_reason("validate_static_web") is None
    assert policy.restriction_reason(
        "run_command",
        {"purpose": "diagnostic"},
    ) is not None
    assert policy.restriction_reason(
        "run_command",
        {"purpose": "acceptance"},
    ) is None
    assert plan.get_current_step().id == 1
    assert plan.completed_history == []
