import pytest

from ..agent.routing import ExecutionMode
from ..agent.routing import TaskRouter


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
    assert route.fallback_used is True


def test_runtime_word_alone_does_not_force_complex_mode():
    route = TaskRouter().route("Fix runtime error in helper.py")

    assert route.mode == ExecutionMode.STANDARD


@pytest.mark.parametrize(
    "prompt",
    [
        "How can I add a button to app.py?",
        "Explain how to refactor app.py",
        "分析一下 app.py 为什么无法运行",
    ],
)
def test_informational_questions_do_not_require_coding_action(prompt):
    assert TaskRouter().route(prompt).requires_coding_action is False


def test_explicit_change_request_requires_coding_action():
    assert TaskRouter().route("Please fix app.py now").requires_coding_action is True
