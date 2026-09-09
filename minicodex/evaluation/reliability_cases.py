"""Named behavior-first reliability benchmark catalog."""

from dataclasses import dataclass

from ..agent.routing import ExecutionMode


@dataclass(frozen=True)
class BehaviorBenchmark:
    case_id: str
    prompt: str
    expected_mode: ExecutionMode
    max_llm_calls: int | None
    max_inspections_before_action: int
    requires_plan: bool


BENCHMARKS = (
    BehaviorBenchmark("fast_hello", "Create try_code/hello.html with Hello World.", ExecutionMode.FAST, 3, 1, False),
    BehaviorBenchmark("fast_readme", "Update README.md with setup instructions.", ExecutionMode.FAST, 3, 1, False),
    BehaviorBenchmark("fast_button_color", "Change the button color in try_code/index.html.", ExecutionMode.FAST, 4, 2, False),
    BehaviorBenchmark("fast_python_bug", "Fix a simple Python bug in helper.py.", ExecutionMode.FAST, 5, 2, False),
    BehaviorBenchmark("fast_tetris", "Create a Tetris game in try_code/tetris.html.", ExecutionMode.FAST, 5, 2, False),
    BehaviorBenchmark("fast_snake", "Create a Snake game under try_code/snake.html.", ExecutionMode.FAST, 5, 2, False),
    BehaviorBenchmark("fast_existing_tetris", "Fix the existing Tetris in try_code/tetris.html.", ExecutionMode.FAST, 5, 2, False),
    BehaviorBenchmark("standard_fastapi", "Add a FastAPI endpoint across several files and tests.", ExecutionMode.STANDARD, 10, 3, True),
    BehaviorBenchmark("standard_three_file", "Implement a feature across app/a.py app/b.py and tests/test_a.py.", ExecutionMode.STANDARD, 10, 3, True),
    BehaviorBenchmark("standard_medium_bug", "Fix a medium bug with focused regression tests.", ExecutionMode.STANDARD, 10, 3, True),
    BehaviorBenchmark("complex_async", "Refactor async runtime cancellation architecture.", ExecutionMode.COMPLEX, None, 3, True),
    BehaviorBenchmark("complex_validation", "Refactor validation architecture and completion routing.", ExecutionMode.COMPLEX, None, 3, True),
)


FAILURE_BENCHMARKS = (
    "stale_patch_targeted_read_retry",
    "validation_fail_fix_revalidate",
    "missing_dependency_manifest_resolve",
    "unsafe_command_safe_alternative",
)
