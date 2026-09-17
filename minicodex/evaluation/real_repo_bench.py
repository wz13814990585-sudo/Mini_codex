"""Opt-in autonomous benchmark with independent, deterministic workspace oracles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .harness import EvaluationHarness
from .models import EvaluationCase, EvaluationCheck
from ..main import build_agent
from ..workspace import WorkspaceConfig


@dataclass(frozen=True)
class RepoFixture:
    case: EvaluationCase
    files: tuple[tuple[str, str], ...]


def _python_bug(case_id="python_double_bug"):
    return RepoFixture(EvaluationCase(case_id,
        "Fix src/pkg/maths.py so double(value) returns value * 2. Preserve the public function name and signature.",
        (EvaluationCheck("python_assertion", command="from pkg.maths import double; assert double(0)==0; assert double(3)==6; assert double(-4)==-8"),),
        tags=("python", "bug_fix")),
        (("src/pkg/maths.py", "def double(value):\n    return value + 2\n"),
         ("benchmark_oracle/test_double.py", "from pkg.maths import double\ndef test_double(): assert double(7) == 14\n")))


def _web_case(case_id, *, keyboard=False):
    task = ("Make pressing ArrowLeft change #state text from idle to left."
            if keyboard else "Make clicking #move change #state text from idle to moved.")
    expected = "ArrowLeft" if keyboard else "addEventListener('click'"
    return RepoFixture(EvaluationCase(case_id, task,
        (EvaluationCheck("file_contains", path="index.html", expected=expected),
         EvaluationCheck("file_contains", path="index.html", expected="#state")), tags=("web", "ui")),
        (("index.html", "<button id='move'>Move</button><div id='state'>idle</div><script></script>"),))


def _api_case(case_id):
    return RepoFixture(EvaluationCase(case_id,
        "Implement POST /login. Wrong credentials return HTTP 401; demo/demo returns HTTP 200 with a token field.",
        (EvaluationCheck("python_assertion", command=(
            "from app import login; assert login('bad','bad')[0] == 401; "
            "status, body = login('demo','demo'); assert status == 200 and 'token' in body")),), tags=("fastapi", "api")),
        (("app.py", "def login(user, password):\n    return 200, {}\n"),
         ("benchmark_oracle/test_login.py", "from app import login\ndef test_login(): assert login('x','x')[0] == 401\n")))


def _typescript_case(case_id, task):
    return RepoFixture(EvaluationCase(case_id, task,
        (EvaluationCheck("file_contains", path="src/app.ts", expected="export"),
         EvaluationCheck("file_not_contains", path="src/app.ts", expected="TODO")), tags=("typescript", task.split()[0])),
        (("package.json", '{"scripts":{"test":"echo test"}}'), ("src/app.ts", "export const value = 1; // TODO\n")))


def fixtures() -> tuple[RepoFixture, ...]:
    """Twenty-six explicit coding tasks; none pre-script model tool calls."""
    result = [_python_bug(), _api_case("api_login"), _web_case("web_move"), _web_case("web_keyboard", keyboard=True)]
    result.extend(_python_bug(f"python_double_{index:02}") for index in range(1, 7))
    result.extend(_api_case(f"api_login_{index:02}") for index in range(1, 6))
    result.extend(_web_case(f"web_move_{index:02}") for index in range(1, 5))
    result.extend(_web_case(f"web_keyboard_{index:02}", keyboard=True) for index in range(1, 4))
    result.extend(_typescript_case(f"typescript_{index:02}", task) for index, task in enumerate((
        "Fix the exported value implementation.", "Add a small exported feature.",
        "Refactor without leaving TODO markers.", "Follow up by removing the TODO marker."), 1))
    return tuple(result)


def run_real_repo_bench(root, *, model_factory, output_level="normal", case_ids=()):
    """Run only with an explicitly supplied autonomous provider model."""
    if model_factory is None:
        raise ValueError("RealRepoBench is opt-in and requires model_factory(case, workspace).")
    catalog = {fixture.case.case_id: fixture for fixture in fixtures()}
    selected = [catalog[case_id] for case_id in case_ids] if case_ids else list(catalog.values())
    def factory(case):
        fixture, workspace = catalog[case.case_id], Path(root) / case.case_id
        workspace.mkdir(parents=True, exist_ok=True)
        for path, content in fixture.files:
            target = workspace / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        agent, _trace, _memory = build_agent(WorkspaceConfig.create(workspace),
            llm=model_factory(case, workspace), output_level=output_level)
        return agent
    return EvaluationHarness(agent_factory=factory).run_suite(
        run_name="real_repo_bench", cases=[fixture.case for fixture in selected])
