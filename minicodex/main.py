from pathlib import Path
import argparse

from dotenv import load_dotenv

from .agent.agent import MiniCodexAgent
from .agent.memory import (
    LongTermMemoryStore,
    attach_long_term_memory,
)
from .agent.planning import Planner, Replanner
from .agent.context import RepoMap, SymbolIndex
from .agent.safety import (
    SandboxLimits,
    SandboxRunner,
)
from .agent.observability import (
    TraceRecorder,
    attach_runtime_tracing,
)

from .llm.client import LLMClient

from .tools.registry import ToolRegistry
from .tools.filesystem import ListFilesTool, ReadFileTool
from .tools.search import SearchCodeTool, SearchSymbolTool
from .tools.editing import PatchFileTool, ReplaceLinesTool, ReplaceSymbolTool, WriteFileTool
from .tools.execution import InstallPythonPackageTool, RunCommandTool, RunTestsTool
from .tools.validation import ValidateBrowserAppTool, ValidateStaticWebTool
from .tools.planning import CompletePlanStepTool, ReplanTool
from .tools.git import GitDiffTool, GitStatusTool


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

load_dotenv(
    PROJECT_ROOT
    / ".env"
)


def main(output_level: str = "normal"):

    # =========================================================
    # Shared Workspace
    # =========================================================

    workspace = (
        PROJECT_ROOT
    )

    # =========================================================
    # LLM
    # =========================================================

    llm = (
        LLMClient()
    )

    # =========================================================
    # Stage 17 Shared Process Sandbox
    # =========================================================

    sandbox = (
        SandboxRunner(
            workspace=(
                workspace
            ),
            limits=(
                SandboxLimits(
                    timeout_seconds=60,
                    max_output_bytes=(
                        1_000_000
                    ),
                    max_file_bytes=(
                        32
                        * 1024
                        * 1024
                    ),
                    max_cpu_seconds=30,
                    max_memory_bytes=(
                        1024
                        * 1024
                        * 1024
                    ),
                )
            ),
        )
    )

    # =========================================================
    # Tool Registry
    # =========================================================

    registry = (
        ToolRegistry()
    )

    # =========================================================
    # Read / Navigation
    # =========================================================

    registry.register(
        ListFilesTool(
            workspace
        )
    )

    registry.register(
        ReadFileTool(
            workspace
        )
    )

    registry.register(
        SearchCodeTool(
            workspace
        )
    )

    # =========================================================
    # Symbol Index
    # =========================================================

    symbol_index = (
        SymbolIndex(
            workspace=workspace,
            max_files=500,
        )
    )

    registry.register(
        SearchSymbolTool(
            symbol_index=(
                symbol_index
            )
        )
    )

    # =========================================================
    # Edit Tools
    # =========================================================

    registry.register(
        PatchFileTool(
            workspace
        )
    )

    registry.register(
        ReplaceLinesTool(
            workspace
        )
    )

    registry.register(
        ReplaceSymbolTool(
            workspace=workspace,
            symbol_index=(
                symbol_index
            ),
        )
    )

    registry.register(
        WriteFileTool(
            workspace
        )
    )

    # =========================================================
    # Stage 17 Sandboxed Execution / Validation
    # =========================================================

    registry.register(
        RunCommandTool(
            workspace=workspace,
            timeout=30,
            sandbox=(
                sandbox
            ),
        )
    )

    registry.register(
        RunTestsTool(
            workspace=workspace,
            timeout=60,
            sandbox=(
                sandbox
            ),
        )
    )

    registry.register(
        InstallPythonPackageTool(
            workspace=workspace,
            timeout=120,
            sandbox=sandbox,
        )
    )

    registry.register(
        ValidateStaticWebTool(
            workspace=workspace,
            timeout=30,
            sandbox=sandbox,
        )
    )

    if ValidateBrowserAppTool.available():
        registry.register(ValidateBrowserAppTool(workspace=workspace))

    # =========================================================
    # Repository Map
    # =========================================================

    repo_map = (
        RepoMap(
            workspace=workspace,
            max_depth=4,
            max_files=200,
        )
    )

    # =========================================================
    # Planner
    # =========================================================

    planner = (
        Planner(
            llm=llm
        )
    )

    replanner = (
        Replanner(
            llm=llm
        )
    )

    # =========================================================
    # Agent
    # =========================================================

    agent = (
        MiniCodexAgent(
            llm=llm,
            registry=registry,
            planner=planner,
            replanner=replanner,
            repo_map=repo_map,
            max_steps=20,
            output_level=output_level,
        )
    )

    # =========================================================
    # Stage 14 Event / Trace
    # =========================================================

    trace_recorder = (
        TraceRecorder(
            max_events=5000
        )
    )

    attach_runtime_tracing(
        agent,
        recorder=(
            trace_recorder
        ),
    )

    # =========================================================
    # Stage 16 Long-Term Memory
    # =========================================================

    long_term_memory = (
        LongTermMemoryStore(
            path=(
                PROJECT_ROOT
                / ".minicodex"
                / "memory"
                / "long_term.json"
            ),
            repository_key=(
                PROJECT_ROOT.name
            ),
            max_records=200,
        )
    )

    attach_long_term_memory(
        agent,
        store=(
            long_term_memory
        ),
        retrieval_limit=5,
    )

    # =========================================================
    # Stage 11 Git Awareness Tools
    # =========================================================

    registry.register(
        GitStatusTool(
            awareness=(
                agent.git_awareness
            )
        )
    )

    registry.register(
        GitDiffTool(
            inspector=(
                agent.git_inspector
            )
        )
    )

    # =========================================================
    # Agent Callback Tools
    # =========================================================

    registry.register(
        CompletePlanStepTool(
            callback=(
                agent.complete_plan_step
            )
        )
    )

    registry.register(
        ReplanTool(
            callback=(
                agent.replan
            )
        )
    )

    # =========================================================
    # CLI
    # =========================================================

    while True:

        user_input = input(
            "\nYou > "
        ).strip()

        if (
            user_input.lower()
            in {
                "exit",
                "quit",
            }
        ):

            break

        if not (
            user_input
        ):

            continue

        result = (
            agent.run(
                user_input,
            )
        )

        print(
            f"\nMiniCodex >\n"
            f"{result}"
        )

        if output_level == "debug":
            # Debug-only internal trace summary.

            trace_summary = trace_recorder.summary()

            print("\n[Trace Summary]")

            print(f"Task ID: {trace_summary.task_id}")

            print(f"Events: {trace_summary.total_events}")

            print(f"LLM Calls: {trace_summary.llm_calls}")

            print(f"Tool Calls: {trace_summary.tool_calls}")

            print(f"Edits: {trace_summary.edits}")

            print(f"Validation Runs: {trace_summary.validation_runs}")

            print(f"Rollbacks: {trace_summary.rollbacks}")

            print(f"Replans: {trace_summary.replans}")

            print(f"Safety Blocks: {trace_summary.safety_blocks}")

        # =====================================================
        # Long-Term Memory
        # =====================================================

            print(
                "[Long-Term Memory] "
                f"{len(long_term_memory.records)} stored task experiences."
            )

        # =====================================================
        # Persist Latest Trace
        # =====================================================

        trace_recorder.save_jsonl(
            PROJECT_ROOT
            / ".minicodex"
            / "traces"
            / "latest.jsonl"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiniCodex interactive coding agent")
    parser.add_argument(
        "--output",
        choices=("normal", "verbose", "debug"),
        default="normal",
        help="terminal detail level (default: normal)",
    )
    main(output_level=parser.parse_args().output)
