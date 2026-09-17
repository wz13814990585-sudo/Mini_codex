"""Canonical import and root-layout contracts."""

from pathlib import Path
import ast
import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", [
    "minicodex.agent.progress", "minicodex.agent.runtime", "minicodex.agent.task_state",
    "minicodex.agent.context.workspace_session", "minicodex.agent.validation.test_index",
])
def test_domain_imports_in_fresh_interpreter(module):
    result = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_major_domain_apis_import_without_cycles():
    from ..agent.agent import MiniCodexAgent
    from ..agent.editing import EditRetryPolicy
    from ..agent.progress import ProgressSignal
    from ..agent.routing import TaskIntent, TaskRouter
    from ..agent.runtime import ToolExecutor
    from ..agent.validation import ValidationPipeline
    from ..tools.registry import ToolRegistry

    assert all(
        value is not None
        for value in (
            MiniCodexAgent,
            EditRetryPolicy,
            ProgressSignal,
            TaskIntent,
            TaskRouter,
            ToolExecutor,
            ValidationPipeline,
            ToolRegistry,
        )
    )


def test_agent_root_contains_only_cross_domain_modules():
    root = Path(__file__).parents[1] / "agent"
    assert {path.name for path in root.glob("*.py")} == {
        "__init__.py",
        "agent.py",
        "reason_codes.py",
        "task_state.py",
    }


def test_tools_root_contains_only_framework_modules():
    root = Path(__file__).parents[1] / "tools"
    assert {path.name for path in root.glob("*.py")} == {
        "__init__.py",
        "base.py",
        "registry.py",
        "results.py",
    }


def test_tools_and_utils_dependency_direction():
    package = Path(__file__).parents[1]
    for domain, forbidden in (("tools", "orchestration"), ("utils", "agent")):
        for path in (package / domain).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                modules = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names] if isinstance(node, ast.Import) else []
                assert not any(forbidden in module.split(".") for module in modules), path


def test_task_state_has_no_production_field_writes_outside_reducer():
    root = Path(__file__).parents[1] / "agent"
    for path in root.rglob("*.py"):
        if path.name == "task_state.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
            for target in targets:
                assert not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Attribute)
                            and target.value.attr == "task_state"), (path, node.lineno)


def test_verification_and_batch_have_one_canonical_path():
    root = Path(__file__).parents[1]
    assert not (root / "tools/planning/complete_plan_step.py").exists()
    pipeline = (root / "agent/validation/pipeline.py").read_text()
    assert "class ValidationState" not in pipeline
    assert "class ValidationEvidence" not in pipeline
    assert "DecisionPolicy" not in pipeline and "CompletionGate" not in pipeline
    batch = (root / "agent/orchestration/tool_batch_runner.py").read_text()
    assert "task_requirements" not in batch and "validation_pipeline" not in batch
    assert len(batch.splitlines()) < 60


def test_workspace_intelligence_is_task_independent():
    root = Path(__file__).parents[1] / "agent/context"
    for name in ("workspace_session.py", "repo_map.py", "symbol_index.py"):
        source = (root / name).read_text()
        assert "MiniCodexAgent" not in source and "run_agent_loop" not in source
    from ..agent.context.workspace_session import WorkspaceSession
    session = WorkspaceSession(root)
    assert not {"task_state", "task_requirements", "validation_pipeline", "active_plan", "latest_blocker"} & vars(session).keys()
