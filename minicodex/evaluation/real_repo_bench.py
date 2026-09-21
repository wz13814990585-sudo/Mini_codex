"""Compatibility entry point for the canonical Benchmark V1 catalog."""

from __future__ import annotations

from pathlib import Path
import shutil

from .benchmark_v1 import BenchmarkFixture as RepoFixture
from .benchmark_v1 import fixtures
from .harness import EvaluationHarness
from ..main import build_agent
from ..workspace import WorkspaceConfig


def _materialize(files, root: Path) -> None:
    for relative, content in files:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def run_real_repo_bench(root, *, model_factory, output_level="normal", case_ids=()):
    """Run Benchmark V1 with an explicitly supplied autonomous provider model.

    Prefer :mod:`minicodex.evaluation.run_benchmark` for versioned multi-run
    experiments. This function remains for existing provider integrations.
    """
    if model_factory is None:
        raise ValueError("RealRepoBench is opt-in and requires model_factory(case, workspace).")
    catalog = {fixture.case.case_id: fixture for fixture in fixtures()}
    selected = [catalog[case_id] for case_id in case_ids] if case_ids else list(catalog.values())

    def factory(case):
        fixture = catalog[case.case_id]
        workspace = Path(root) / case.case_id
        workspace.mkdir(parents=True, exist_ok=True)
        _materialize(fixture.workspace_files, workspace)
        oracle_root = Path(root) / ".oracle" / case.case_id
        agent, recorder, _memory = build_agent(
            WorkspaceConfig.create(workspace),
            llm=model_factory(case, workspace),
            output_level=output_level,
        )
        agent._benchmark_oracle_root = oracle_root
        agent._benchmark_materialize_oracle = lambda: _materialize(fixture.oracle_files, oracle_root)
        agent._benchmark_cleanup_oracle = lambda: (
            shutil.rmtree(oracle_root)
            if oracle_root.is_dir() and oracle_root.parent.name == ".oracle"
            else None
        )
        agent._benchmark_recorder = recorder
        agent._benchmark_trace_path = str(Path(root) / ".traces" / f"{case.case_id}.jsonl")
        return agent

    return EvaluationHarness(agent_factory=factory, profile="minicodex").run_suite(
        run_name="real_repo_bench", cases=[fixture.case for fixture in selected]
    )
