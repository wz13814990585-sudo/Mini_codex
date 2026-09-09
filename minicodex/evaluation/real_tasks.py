"""Fixed 30-task vibecoding catalog for deterministic and live evaluation."""

from dataclasses import dataclass

from ..agent.routing import ExecutionMode
from ..agent.routing import TaskIntent


@dataclass(frozen=True)
class RealTaskCase:
    case_id: str
    category: str
    prompt: str
    expected_intent: TaskIntent
    expected_mode: ExecutionMode
    expected_terminal_kind: str = "task_report"


def _case(case_id, category, prompt, intent, mode, terminal="task_report"):
    return RealTaskCase(case_id, category, prompt, intent, mode, terminal)


REAL_TASKS = (
    _case("create_hello", "create", "Create try_code/hello.html with Hello World.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("create_tetris", "create", "Create a Tetris game in try_code/tetris.html.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("create_snake", "create", "Create a Snake game in try_code/snake.html.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("create_cli", "create", "Create a small Python CLI in examples/cli.py.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("create_fastapi", "create", "Create a FastAPI endpoint across several files and tests.", TaskIntent.MODIFY, ExecutionMode.STANDARD),
    _case("create_utility", "create", "Create a utility module in examples/formatting.py.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("create_config", "create", "Create configuration across app/config.py app/main.py and tests/test_config.py.", TaskIntent.MODIFY, ExecutionMode.STANDARD),
    _case("create_tests", "create", "Create tests/test_parser.py for parser.py.", TaskIntent.MODIFY, ExecutionMode.STANDARD),
    _case("modify_css", "modify", "Change the button CSS in try_code/index.html.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("modify_function", "modify", "Add validation to one existing Python function.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("modify_endpoint", "modify", "Update FastAPI endpoint behavior across several files.", TaskIntent.MODIFY, ExecutionMode.STANDARD),
    _case("modify_config", "modify", "Update try_code/config.json.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("modify_logging", "modify", "Add logging to examples/worker.py.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("modify_rename", "modify", "Rename behavior across several files.", TaskIntent.MODIFY, ExecutionMode.STANDARD),
    _case("modify_multifile", "modify", "Implement a change in app/a.py app/b.py and tests/test_a.py.", TaskIntent.MODIFY, ExecutionMode.STANDARD),
    _case("modify_test", "modify", "Update tests/test_service.py for the new behavior.", TaskIntent.MODIFY, ExecutionMode.STANDARD),
    _case("modify_async_architecture", "modify", "Refactor MiniCodex async cancellation architecture.", TaskIntent.MODIFY, ExecutionMode.COMPLEX),
    _case("fix_pytest", "fix", "Fix a simple Python bug causing a pytest failure in examples/helper.py.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("fix_none", "fix", "Fix the None bug in examples/parser.py.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("fix_syntax", "fix", "Fix the syntax bug in examples/cli.py.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("fix_import", "fix", "Fix the bad import in app/service.py.", TaskIntent.MODIFY, ExecutionMode.STANDARD),
    _case("fix_dependency", "fix", "Fix a missing dependency across several files.", TaskIntent.MODIFY, ExecutionMode.STANDARD),
    _case("fix_stale", "fix", "Fix stale code in examples/helper.py.", TaskIntent.MODIFY, ExecutionMode.FAST),
    _case("fix_async", "fix", "Fix an async bug in app/worker.py.", TaskIntent.MODIFY, ExecutionMode.STANDARD),
    _case("fix_regression", "fix", "Fix a regression bug with focused regression tests.", TaskIntent.MODIFY, ExecutionMode.STANDARD),
    _case("inspect_review", "inspect", "Review examples/helper.py but don't modify it.", TaskIntent.INSPECT_ONLY, ExecutionMode.FAST, "inspection_report"),
    _case("inspect_locate", "inspect", "Inspect the project and locate the retry implementation.", TaskIntent.INSPECT_ONLY, ExecutionMode.STANDARD, "inspection_report"),
    _case("inspect_function", "inspect", "Explain examples/helper.py without changing it.", TaskIntent.INSPECT_ONLY, ExecutionMode.FAST, "inspection_report"),
    _case("inspect_traceback", "inspect", "Analyze the traceback in app/service.py without editing.", TaskIntent.INSPECT_ONLY, ExecutionMode.STANDARD, "inspection_report"),
    _case("inspect_architecture", "inspect", "Review the control plane architecture without modifying code.", TaskIntent.INSPECT_ONLY, ExecutionMode.STANDARD, "inspection_report"),
    _case("informational_pytest", "informational", "What does pytest -q mean?", TaskIntent.INFORMATIONAL, ExecutionMode.STANDARD, "informational_answer"),
)


LIVE_METRICS = (
    "intent", "mode", "success", "final_outcome", "false_completion", "wrong_edit",
    "llm_call_count", "tool_call_count", "inspection_count", "calls_before_first_edit",
    "edit_count", "validation_count", "replan_count", "rollback_count",
    "action_required_count", "prompt_tokens", "max_steps_exhausted",
)
