import pytest

from ..agent.execution_mode import ExecutionMode
from ..agent.task_router import TaskRouter


@pytest.mark.parametrize(
    ("task_text", "expected"),
    [
        (
            "Create try_code/hello.html with a Hello World page.",
            ExecutionMode.FAST,
        ),
        (
            "Create try_code/index.html with a playable Tetris-style game.",
            ExecutionMode.FAST,
        ),
        ("Create a Snake game under try_code.", ExecutionMode.FAST),
        ("Update README with setup instructions.", ExecutionMode.FAST),
        (
            "Add input validation to one existing Python function.",
            ExecutionMode.FAST,
        ),
        (
            "Add a FastAPI endpoint across several application files and tests.",
            ExecutionMode.STANDARD,
        ),
        (
            "Refactor MiniCodex async runtime and cancellation architecture.",
            ExecutionMode.COMPLEX,
        ),
        ("Change the button color in try_code/index.html.", ExecutionMode.FAST),
        ("Fix a simple Python bug in helper.py.", ExecutionMode.FAST),
        (
            "Fix the existing Tetris implementation in try_code/tetris.html.",
            ExecutionMode.FAST,
        ),
        (
            "Implement a feature across app/a.py app/b.py and tests/test_a.py.",
            ExecutionMode.STANDARD,
        ),
        (
            "Diagnose and fix a medium bug with focused regression tests.",
            ExecutionMode.STANDARD,
        ),
        (
            "Refactor validation architecture and completion routing.",
            ExecutionMode.COMPLEX,
        ),
    ],
)
def test_benchmark_routing(task_text, expected):
    assert TaskRouter().route(task_text).mode == expected


def test_uncertain_task_routes_standard_not_complex():
    route = TaskRouter().route("Improve the account settings behavior")

    assert route.mode == ExecutionMode.STANDARD
    assert "uncertain" in route.signals[0]
