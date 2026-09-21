import pytest

from ....agent.routing import ExecutionMode
from ....agent.routing import TaskIntent, TaskRouter


@pytest.mark.parametrize(
    ("prompt", "intent", "mode"),
    [
        ("Explain how to fix foo.py", TaskIntent.INFORMATIONAL, ExecutionMode.STANDARD),
        ("Fix foo.py", TaskIntent.MODIFY, ExecutionMode.STANDARD),
        ("Can you fix foo.py?", TaskIntent.MODIFY, ExecutionMode.STANDARD),
        ("Tell me how I should modify foo.py", TaskIntent.INFORMATIONAL, ExecutionMode.STANDARD),
        ("Look at foo.py and fix the bug", TaskIntent.MODIFY, ExecutionMode.STANDARD),
        ("Review foo.py", TaskIntent.INSPECT_ONLY, ExecutionMode.STANDARD),
        ("Review foo.py but do not change anything", TaskIntent.INSPECT_ONLY, ExecutionMode.STANDARD),
        ("Analyze the async runtime architecture", TaskIntent.INSPECT_ONLY, ExecutionMode.COMPLEX),
        ("Refactor the async runtime architecture", TaskIntent.MODIFY, ExecutionMode.COMPLEX),
        ("Fix a runtime error in examples/demo.py", TaskIntent.MODIFY, ExecutionMode.FAST),
        ("Refactor async runtime cancellation architecture", TaskIntent.MODIFY, ExecutionMode.COMPLEX),
    ],
)
def test_intent_and_complexity_are_orthogonal(prompt, intent, mode):
    route = TaskRouter().route(prompt)

    assert route.intent == intent
    assert route.mode == mode


def test_architecture_analysis_can_be_complex_without_being_modify():
    route = TaskRouter().route("Analyze the async runtime cancellation architecture")

    assert route.intent == TaskIntent.INSPECT_ONLY
    assert route.mode == ExecutionMode.COMPLEX
