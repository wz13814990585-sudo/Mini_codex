from pathlib import Path

from ..agent.repo_map import RepoMap


def test_repo_map_builds_basic_structure(
    tmp_path: Path,
):

    src = (
        tmp_path
        / "src"
    )

    tests = (
        tmp_path
        / "tests"
    )

    src.mkdir()
    tests.mkdir()

    (
        tmp_path
        / "README.md"
    ).write_text(
        "# Demo"
    )

    (
        src
        / "app.py"
    ).write_text(
        "print('hello')"
    )

    (
        tests
        / "test_app.py"
    ).write_text(
        "def test_app(): pass"
    )

    repo_map = RepoMap(
        workspace=tmp_path,
        max_depth=4,
        max_files=100,
    )

    result = (
        repo_map.build()
    )

    assert (
        "Repository structure:"
        in result
    )

    assert (
        "README.md"
        in result
    )

    assert (
        "src/"
        in result
    )

    assert (
        "app.py"
        in result
    )

    assert (
        "tests/"
        in result
    )

    assert (
        "test_app.py"
        in result
    )


def test_repo_map_ignores_git(
    tmp_path: Path,
):

    git_dir = (
        tmp_path
        / ".git"
    )

    git_dir.mkdir()

    (
        git_dir
        / "config"
    ).write_text(
        "git config"
    )

    (
        tmp_path
        / "app.py"
    ).write_text(
        "print('ok')"
    )

    result = RepoMap(
        workspace=tmp_path
    ).build()

    assert (
        "app.py"
        in result
    )

    assert (
        ".git"
        not in result
    )


def test_repo_map_ignores_virtual_environment(
    tmp_path: Path,
):

    package_dir = (
        tmp_path
        / ".venv"
        / "lib"
        / "site-packages"
    )

    package_dir.mkdir(
        parents=True
    )

    (
        package_dir
        / "fake_package.py"
    ).write_text(
        "x = 1"
    )

    (
        tmp_path
        / "main.py"
    ).write_text(
        "print('main')"
    )

    result = RepoMap(
        workspace=tmp_path
    ).build()

    assert (
        "main.py"
        in result
    )

    assert (
        ".venv"
        not in result
    )

    assert (
        "fake_package.py"
        not in result
    )


def test_repo_map_ignores_node_modules(
    tmp_path: Path,
):

    node_modules = (
        tmp_path
        / "node_modules"
        / "demo"
    )

    node_modules.mkdir(
        parents=True
    )

    (
        node_modules
        / "index.js"
    ).write_text(
        "module.exports = {}"
    )

    (
        tmp_path
        / "app.js"
    ).write_text(
        "console.log('hello')"
    )

    result = RepoMap(
        workspace=tmp_path
    ).build()

    assert (
        "app.js"
        in result
    )

    assert (
        "node_modules"
        not in result
    )


def test_repo_map_respects_max_depth(
    tmp_path: Path,
):

    level1 = (
        tmp_path
        / "a"
    )

    level2 = (
        level1
        / "b"
    )

    level3 = (
        level2
        / "c"
    )

    level3.mkdir(
        parents=True
    )

    (
        level1
        / "one.py"
    ).write_text(
        "1"
    )

    (
        level2
        / "two.py"
    ).write_text(
        "2"
    )

    (
        level3
        / "three.py"
    ).write_text(
        "3"
    )

    result = RepoMap(
        workspace=tmp_path,
        max_depth=2,
    ).build()

    assert (
        "one.py"
        in result
    )

    assert (
        "two.py"
        in result
    )

    assert (
        "three.py"
        not in result
    )


def test_repo_map_respects_max_files(
    tmp_path: Path,
):

    for index in range(
        10
    ):

        (
            tmp_path
            / f"file_{index}.py"
        ).write_text(
            str(index)
        )

    result = RepoMap(
        workspace=tmp_path,
        max_files=3,
    ).build()

    file_lines = [
        line
        for line
        in result.splitlines()
        if ".py" in line
    ]

    assert (
        len(file_lines)
        == 3
    )

    assert (
        "limited to 3 files"
        in result
    )


def test_repo_map_empty_repository(
    tmp_path: Path,
):

    result = RepoMap(
        workspace=tmp_path
    ).build()

    assert (
        result
        == "Repository appears empty."
    )


def test_repo_map_missing_workspace(
    tmp_path: Path,
):

    missing = (
        tmp_path
        / "does_not_exist"
    )

    result = RepoMap(
        workspace=missing
    ).build()

    assert (
        result
        == (
            "Repository map unavailable: "
            "workspace does not exist."
        )
    )


def test_repo_map_workspace_is_file(
    tmp_path: Path,
):

    path = (
        tmp_path
        / "file.txt"
    )

    path.write_text(
        "hello"
    )

    result = RepoMap(
        workspace=path
    ).build()

    assert (
        result
        == (
            "Repository map unavailable: "
            "workspace is not a directory."
        )
    )

from pathlib import Path

from ..agent.agent import MiniCodexAgent
from ..agent.repo_map import RepoMap
from ..llm.types import (
    LLMResponse,
    TokenUsage,
)


class FakeMessage:

    def __init__(
        self,
        content="Done.",
    ):

        self.content = content
        self.tool_calls = []

    def model_dump(
        self,
        exclude_none=True,
    ):

        return {
            "role": "assistant",
            "content": self.content,
        }


class FakeRegistry:

    def get_schemas(
        self,
    ) -> list:

        return []

    def execute(
        self,
        name,
        arguments,
    ):

        raise AssertionError(
            "No tool should be executed."
        )


def _combined_messages(
    messages,
) -> str:

    return "\n".join(
        str(
            message.get(
                "content",
                "",
            )
        )
        for message
        in messages
    )


def test_repo_map_is_visible_to_llm(
    tmp_path: Path,
):

    src = (
        tmp_path
        / "src"
    )

    src.mkdir()

    (
        src
        / "service.py"
    ).write_text(
        "class Service: pass"
    )

    repo_map = RepoMap(
        workspace=tmp_path
    )

    class InspectingLLM:

        def __init__(
            self,
        ):

            self.seen = False

        def chat(
            self,
            messages,
            tools=None,
        ):

            combined = (
                _combined_messages(
                    messages
                )
            )

            assert (
                "Repository map:"
                in combined
            )

            assert (
                "src/"
                in combined
            )

            assert (
                "service.py"
                in combined
            )

            self.seen = True

            return LLMResponse(
                message=FakeMessage(
                    content="Done."
                ),
                usage=TokenUsage(
                    prompt_tokens=100,
                    completion_tokens=10,
                    total_tokens=110,
                ),
            )

    llm = (
        InspectingLLM()
    )

    agent = MiniCodexAgent(
        llm=llm,
        registry=FakeRegistry(),
        planner=None,
        replanner=None,
        repo_map=repo_map,
        max_steps=1,
    )

    result = agent.run(
        "Inspect the project.",
        use_planning=False,
    )

    assert (
        result
        == "Done."
    )

    assert (
        llm.seen
        is True
    )


def test_repo_map_rebuilds_between_tasks(
    tmp_path: Path,
):

    (
        tmp_path
        / "first.py"
    ).write_text(
        "x = 1"
    )

    repo_map = RepoMap(
        workspace=tmp_path
    )

    class MultiTaskLLM:

        def __init__(
            self,
        ):

            self.call_count = 0

        def chat(
            self,
            messages,
            tools=None,
        ):

            self.call_count += 1

            combined = (
                _combined_messages(
                    messages
                )
            )

            if (
                self.call_count
                == 1
            ):

                assert (
                    "first.py"
                    in combined
                )

                assert (
                    "second.py"
                    not in combined
                )

            elif (
                self.call_count
                == 2
            ):

                assert (
                    "first.py"
                    in combined
                )

                assert (
                    "second.py"
                    in combined
                )

            else:

                raise AssertionError(
                    "Unexpected LLM call."
                )

            return LLMResponse(
                message=FakeMessage(
                    content="Done."
                ),
                usage=TokenUsage(
                    prompt_tokens=100,
                    completion_tokens=10,
                    total_tokens=110,
                ),
            )

    llm = (
        MultiTaskLLM()
    )

    agent = MiniCodexAgent(
        llm=llm,
        registry=FakeRegistry(),
        planner=None,
        replanner=None,
        repo_map=repo_map,
        max_steps=1,
    )

    agent.run(
        "Task one.",
        use_planning=False,
    )

    (
        tmp_path
        / "second.py"
    ).write_text(
        "y = 2"
    )

    agent.run(
        "Task two.",
        use_planning=False,
    )


def test_turn_context_refreshes_repo_map(
    tmp_path: Path,
):

    (
        tmp_path
        / "old.py"
    ).write_text(
        "x = 1"
    )

    repo_map = RepoMap(
        workspace=tmp_path
    )

    agent = MiniCodexAgent(
        llm=None,
        registry=FakeRegistry(),
        planner=None,
        replanner=None,
        repo_map=repo_map,
    )

    agent._refresh_repo_map()

    assert (
        "old.py"
        in agent.repo_map_text
    )

    assert (
        "new.py"
        not in agent.repo_map_text
    )

    # Simulate a file created during the task.
    (
        tmp_path
        / "new.py"
    ).write_text(
        "y = 2"
    )

    # Every dynamic turn context refreshes the map.
    context = (
        agent._build_turn_context(
            plan=None,
            current_step=None,
            remaining_agent_steps=10,
        )
    )

    assert (
        "new.py"
        in agent.repo_map_text
    )

    assert (
        "new.py"
        in context
    )


def test_repo_map_failure_does_not_crash_agent(
    tmp_path: Path,
):

    missing = (
        tmp_path
        / "missing"
    )

    repo_map = RepoMap(
        workspace=missing
    )

    agent = MiniCodexAgent(
        llm=None,
        registry=FakeRegistry(),
        planner=None,
        replanner=None,
        repo_map=repo_map,
    )

    agent._refresh_repo_map()

    assert (
        "Repository map unavailable"
        in agent.repo_map_text
    )