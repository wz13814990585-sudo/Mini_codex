"""Behavior-first real task catalog for local and live-model evaluation."""

from dataclasses import dataclass

from ..agent.execution_mode import ExecutionMode


@dataclass(frozen=True)
class RealTaskCase:
    case_id: str
    prompt: str
    expected_mode: ExecutionMode
    expected_terminal_kind: str = "task_report"


REAL_TASKS = (
    RealTaskCase("fast_hello", "Create try_code/hello.html with Hello World.", ExecutionMode.FAST),
    RealTaskCase("fast_readme", "Update README.md setup instructions.", ExecutionMode.FAST),
    RealTaskCase("fast_css", "Change the button color in try_code/index.html.", ExecutionMode.FAST),
    RealTaskCase("fast_python_bug", "Fix a simple Python bug in helper.py.", ExecutionMode.FAST),
    RealTaskCase("fast_tetris", "Create Tetris in try_code/tetris.html.", ExecutionMode.FAST),
    RealTaskCase("fast_snake", "Create Snake in try_code/snake.html.", ExecutionMode.FAST),
    RealTaskCase("fast_satisfied", "Fix the existing Tetris in try_code/tetris.html.", ExecutionMode.FAST),
    RealTaskCase("fast_stale_patch", "Fix stale code in examples/helper.py.", ExecutionMode.FAST),
    RealTaskCase("fast_failed_test", "Fix the failed test bug in examples/helper.py.", ExecutionMode.FAST),
    RealTaskCase("standard_endpoint", "Add a FastAPI endpoint across several files and tests.", ExecutionMode.STANDARD),
    RealTaskCase("standard_three_files", "Implement a feature across app/a.py app/b.py and tests/test_a.py.", ExecutionMode.STANDARD),
    RealTaskCase("standard_regression", "Fix a medium regression bug with focused regression tests.", ExecutionMode.STANDARD),
    RealTaskCase("standard_config", "Add a configuration feature across app/config.py app/main.py and tests/test_config.py.", ExecutionMode.STANDARD),
    RealTaskCase("complex_cancellation", "Refactor async runtime cancellation architecture.", ExecutionMode.COMPLEX),
    RealTaskCase("complex_validation", "Refactor validation architecture and completion routing.", ExecutionMode.COMPLEX),
    RealTaskCase("complex_control_plane", "Redesign the MiniCodex control plane state machine.", ExecutionMode.COMPLEX),
    RealTaskCase("informational", "Explain what pytest -q does.", ExecutionMode.STANDARD, "informational_answer"),
)


LIVE_METRICS = (
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
)
