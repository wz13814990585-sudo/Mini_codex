"""Opt-in autonomous coding evaluation; never used by deterministic CI."""

from __future__ import annotations

from pathlib import Path

from .harness import EvaluationHarness
from .vibebench import scenarios
from ..agent.agent import MiniCodexAgent
from ..tools.registry import ToolRegistry
from ..tools.editing import PatchFileTool, WriteFileTool
from ..tools.filesystem import ReadFileTool
from ..tools.execution import RunCommandTool, RunTestsTool
from ..tools.validation.validate_static_web import ValidateStaticWebTool
from ..tools.validation.validate_service import ValidateServiceTool


def run_real_vibebench(root, *, model_factory, output_level="normal", case_ids=()):
    """Run fixtures with a provider-supplied autonomous model, never scripts.

    ``model_factory(case, workspace)`` is intentionally provider-neutral. It
    receives no expected tool calls; the ordinary agent loop supplies only the
    user request, workspace facts, and registered tool schemas.
    """
    if model_factory is None:
        raise ValueError("RealVibeBench is opt-in and requires model_factory(case, workspace).")
    catalog = {scenario.case.case_id: scenario for scenario in scenarios()}
    selected = [catalog[case_id] for case_id in case_ids] if case_ids else list(catalog.values())

    def factory(case):
        scenario = catalog[case.case_id]
        workspace = Path(root) / case.case_id
        workspace.mkdir(parents=True, exist_ok=True)
        for path, content in scenario.files:
            file = workspace / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        registry = ToolRegistry()
        for tool in (ReadFileTool, PatchFileTool, WriteFileTool, RunCommandTool,
                     RunTestsTool, ValidateStaticWebTool, ValidateServiceTool):
            registry.register(tool(workspace))
        return MiniCodexAgent(llm=model_factory(case, workspace), registry=registry,
                              planner=None, status_interval_seconds=0, output_level=output_level)

    return EvaluationHarness(agent_factory=factory).run_suite(
        run_name="real_vibebench", cases=[scenario.case for scenario in selected]
    )
