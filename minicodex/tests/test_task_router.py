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


@pytest.mark.parametrize("prompt", [
    "创建一个贪吃蛇小游戏",
    "Build a browser game",
    "创建一个网页",
])
def test_unspecified_web_creation_gets_a_conventional_target(prompt):
    route = TaskRouter().route(prompt)
    assert route.requires_coding_action
    assert route.target_paths == ("index.html",)

    from ..agent.planning.requirements import RequirementsExtractor
    requirements = RequirementsExtractor().extract(
        prompt, mode=route.mode, target_paths=route.target_paths,
    )
    assert requirements.items[0].contract.path == "index.html"


def test_explicit_creation_path_wins_over_default():
    route = TaskRouter().route("创建一个贪吃蛇游戏，保存到 games/snake.html")
    assert route.target_paths == ("games/snake.html",)


def test_directory_hint_is_preserved_for_unspecified_web_filename():
    route = TaskRouter().route("Create a Snake game under try_code")
    assert route.target_paths == ("try_code/index.html",)


@pytest.mark.parametrize("prompt", [
    "创建一个 Python 命令行贪吃蛇游戏",
    "创建一个 Python 贪吃蛇游戏",
])
def test_python_game_does_not_get_a_browser_target(prompt):
    route = TaskRouter().route(prompt)
    assert route.target_paths == ()


def test_external_workspace_limit_does_not_make_creation_read_only():
    route = TaskRouter().route("创建一个网页，不要修改工作区外的文件")
    assert route.requires_coding_action
    assert route.target_paths == ("index.html",)


def test_global_no_edit_still_forces_read_only():
    route = TaskRouter().route("创建一个网页，但不要修改任何文件")
    assert not route.requires_coding_action
