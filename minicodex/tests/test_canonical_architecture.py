"""Canonical import and root-layout contracts."""

from pathlib import Path


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
