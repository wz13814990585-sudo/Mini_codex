"""CLI composition root for an arbitrary local coding workspace."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from .agent.agent import MiniCodexAgent
from .agent.context import RepoMap, SymbolIndex
from .agent.memory import LongTermMemoryStore, attach_long_term_memory
from .agent.observability import TraceRecorder, attach_runtime_tracing
from .agent.planning import Planner, Replanner, RequirementsExtractor
from .agent.routing import TaskRouter
from .agent.safety import SandboxLimits, SandboxRunner
from .agent.validation import SemanticRegressionJudge
from .llm.client import LLMClient
from .tools.editing import PatchFileTool, ReplaceLinesTool, ReplaceSymbolTool, WriteFileTool
from .tools.execution import InstallPythonPackageTool, RunCommandTool, RunTestsTool
from .tools.filesystem import ListFilesTool, ReadFileTool
from .tools.git import GitDiffTool, GitStatusTool
from .tools.planning import ReplanTool
from .tools.registry import ToolRegistry
from .tools.search import SearchCodeTool, SearchSymbolTool
from .tools.validation import ValidateBrowserAppTool, ValidateSemanticTool, ValidateStaticWebTool
from .tools.validation.validate_service import ValidateServiceTool
from .workspace import WorkspaceConfig


APPLICATION_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(APPLICATION_ROOT / ".env")


def build_agent(config: WorkspaceConfig, *, llm=None, control_llm=None, judge_llm=None,
                output_level="normal") -> tuple[MiniCodexAgent, TraceRecorder, LongTermMemoryStore]:
    """Construct one Harness whose filesystem tools target ``workspace_root``."""
    workspace = config.workspace_root
    llm = llm or LLMClient()
    control_llm = control_llm or (LLMClient(model=os.getenv("DEEPSEEK_CONTROL_MODEL", "").strip())
                                  if os.getenv("DEEPSEEK_CONTROL_MODEL", "").strip() else llm)
    judge_llm = judge_llm or (LLMClient(model=os.getenv("DEEPSEEK_JUDGE_MODEL", "").strip())
                              if os.getenv("DEEPSEEK_JUDGE_MODEL", "").strip() else control_llm)
    sandbox = SandboxRunner(workspace=workspace, limits=SandboxLimits(timeout_seconds=60,
                            max_output_bytes=1_000_000, max_file_bytes=32 * 1024 * 1024,
                            max_cpu_seconds=30, max_memory_bytes=1024 * 1024 * 1024))
    registry = ToolRegistry()
    symbol_index = SymbolIndex(workspace=workspace, max_files=500)
    for tool in (ListFilesTool(workspace), ReadFileTool(workspace), SearchCodeTool(workspace),
                 SearchSymbolTool(symbol_index=symbol_index), PatchFileTool(workspace),
                 ReplaceLinesTool(workspace), ReplaceSymbolTool(workspace=workspace, symbol_index=symbol_index),
                 WriteFileTool(workspace), ValidateServiceTool(workspace),
                 RunCommandTool(workspace=workspace, timeout=30, sandbox=sandbox),
                 RunTestsTool(workspace=workspace, timeout=60, sandbox=sandbox),
                 InstallPythonPackageTool(workspace=workspace, timeout=120, sandbox=sandbox),
                 ValidateStaticWebTool(workspace=workspace, timeout=30, sandbox=sandbox),
                 ValidateSemanticTool(workspace=workspace, llm=judge_llm)):
        registry.register(tool)
    if ValidateBrowserAppTool.available():
        registry.register(ValidateBrowserAppTool(workspace=workspace))
    agent = MiniCodexAgent(llm=llm, registry=registry, planner=Planner(llm=llm),
        replanner=Replanner(llm=llm), repo_map=RepoMap(workspace=workspace, max_depth=4, max_files=200),
        task_router=TaskRouter(llm=control_llm), requirements_extractor=RequirementsExtractor(llm=control_llm),
        semantic_judge=SemanticRegressionJudge(llm=judge_llm), max_steps=20, output_level=output_level)
    recorder = TraceRecorder(max_events=5000)
    attach_runtime_tracing(agent, recorder=recorder)
    memory = LongTermMemoryStore(path=config.runtime_root / "memory" / "long_term.json",
                                 repository_key=config.repository_key, max_records=200)
    attach_long_term_memory(agent, store=memory, retrieval_limit=5)
    registry.register(GitStatusTool(awareness=agent.git_awareness))
    registry.register(GitDiffTool(inspector=agent.git_inspector))
    registry.register(ReplanTool(callback=agent.replan))
    return agent, recorder, memory


def run_interactive(config: WorkspaceConfig, *, output_level="normal") -> None:
    agent, recorder, _memory = build_agent(config, output_level=output_level)
    if output_level in {"verbose", "debug"}:
        print(f"[MiniCodex workspace] {config.workspace_root}")
    while True:
        try:
            user_input = input("\nYou > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if user_input.lower() in {"exit", "quit"}:
            return
        if not user_input:
            continue
        print(f"\nMiniCodex >\n{agent.run(user_input)}")
        config.trace_root.mkdir(parents=True, exist_ok=True)
        recorder.save_jsonl(config.trace_root / "latest.jsonl")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="MiniCodex interactive coding agent")
    parser.add_argument("--workspace", metavar="PATH", help="repository to inspect and edit (default: current directory)")
    parser.add_argument("--output", choices=("normal", "verbose", "debug"), default="normal")
    args = parser.parse_args(argv)
    try:
        config = WorkspaceConfig.create(args.workspace, application_root=APPLICATION_ROOT)
    except ValueError as exc:
        parser.error(str(exc))
    run_interactive(config, output_level=args.output)


if __name__ == "__main__":
    main()
