from ...agent.task_router import TaskRouter
from ...evaluation.real_tasks import LIVE_METRICS, REAL_TASKS


def test_real_task_catalog_covers_required_modes_and_terminal_semantics():
    router = TaskRouter()

    assert len(REAL_TASKS) >= 16
    assert all(router.route(case.prompt).mode == case.expected_mode for case in REAL_TASKS)
    assert {case.expected_terminal_kind for case in REAL_TASKS} == {
        "task_report",
        "informational_answer",
    }


def test_live_metric_contract_captures_execution_efficiency_and_outcome():
    assert {
        "success_rate",
        "llm_calls",
        "tool_calls",
        "calls_before_first_edit",
        "inspection_calls",
        "validation_calls",
        "prompt_tokens",
        "action_required_count",
        "replans",
        "rollbacks",
        "final_outcome",
    } == set(LIVE_METRICS)
