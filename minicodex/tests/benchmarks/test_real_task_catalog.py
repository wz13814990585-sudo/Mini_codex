from ...agent.task_router import TaskRouter
from ...evaluation.real_tasks import LIVE_METRICS, REAL_TASKS


def test_real_task_catalog_covers_required_modes_and_terminal_semantics():
    router = TaskRouter()

    assert len(REAL_TASKS) >= 30
    assert all(router.route(case.prompt).mode == case.expected_mode for case in REAL_TASKS)
    assert all(router.route(case.prompt).intent == case.expected_intent for case in REAL_TASKS)
    assert {case.category for case in REAL_TASKS} == {
        "create", "modify", "fix", "inspect", "informational"
    }
    assert {case.expected_terminal_kind for case in REAL_TASKS} == {
        "task_report",
        "inspection_report",
        "informational_answer",
    }


def test_live_metric_contract_captures_execution_efficiency_and_outcome():
    assert {
        "intent",
        "mode",
        "success",
        "false_completion",
        "wrong_edit",
        "llm_call_count",
        "tool_call_count",
        "calls_before_first_edit",
        "inspection_count",
        "edit_count",
        "validation_count",
        "prompt_tokens",
        "action_required_count",
        "replan_count",
        "rollback_count",
        "final_outcome",
        "max_steps_exhausted",
    } == set(LIVE_METRICS)
