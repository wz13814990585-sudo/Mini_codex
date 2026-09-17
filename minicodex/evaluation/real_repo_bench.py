"""Opt-in autonomous evaluation over small, realistic local repository families."""

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


def fixtures() -> tuple[RepoFixture, ...]:
    """Twenty API-free task definitions across four repository shapes.

    They deliberately contain no scripted calls: a caller supplies an autonomous
    provider model through ``run_real_repo_bench``.
    """
    families = {
        "python": (("src/pkg/maths.py", "def double(value):\n    return value + 2\n"),),
        "fastapi": (("app.py", "# service fixture\n"), ("README.md", "# API\n")),
        "web": (("index.html", "<button id='move'>Move</button><div id='state'>idle</div>"),),
        "typescript": (("src/app.ts", "export const value = 1;\n"), ("package.json", '{"scripts":{"test":"echo tests"}}')),
    }
    tasks = (
        ("python", "bug fix"), ("python", "small feature"), ("python", "multi-file feature"),
        ("python", "refactor"), ("python", "follow-up edit"), ("python", "failing test repair"),
        ("fastapi", "API behavior"), ("fastapi", "invalid login behavior"), ("fastapi", "route refactor"),
        ("fastapi", "documentation update"), ("fastapi", "service feature"),
        ("web", "UI interaction"), ("web", "keyboard interaction"), ("web", "small feature"),
        ("web", "bug fix"), ("web", "follow-up edit"),
        ("typescript", "bug fix"), ("typescript", "small feature"),
        ("typescript", "multi-file feature"), ("typescript", "refactor"),
    )
    return tuple(RepoFixture(
        EvaluationCase(f"{family}_{index:02}", f"In this {family} project, complete the {task} task.",
                       (EvaluationCheck("file_exists", path=files[0][0]),), tags=(family, task)),
        files,
    ) for index, (family, task) in enumerate(tasks, 1) for files in (families[family],))


def run_real_repo_bench(root, *, model_factory, output_level="normal", case_ids=()):
    """Run RealRepoBench only with an explicitly supplied provider model."""
    if model_factory is None:
        raise ValueError("RealRepoBench is opt-in and requires model_factory(case, workspace).")
    catalog = {fixture.case.case_id: fixture for fixture in fixtures()}
    selected = [catalog[case_id] for case_id in case_ids] if case_ids else list(catalog.values())

    def factory(case):
        fixture = catalog[case.case_id]
        workspace = Path(root) / case.case_id
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
