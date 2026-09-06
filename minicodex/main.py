from pathlib import Path

from dotenv import load_dotenv

from .agent.agent import MiniCodexAgent
from .agent.planner import Planner
from .agent.replanner import Replanner
from .agent.repo_map import RepoMap
from .agent.symbol_index import SymbolIndex
from .agent.trace import (
    TraceRecorder,
)
from .agent.trace_runtime import (
    attach_runtime_tracing,
)

from .llm.client import LLMClient

from .tools.registry import ToolRegistry
from .tools.read_file import ReadFileTool
from .tools.list_files import ListFilesTool
from .tools.write_file import WriteFileTool
from .tools.search_code import SearchCodeTool
from .tools.search_symbol import SearchSymbolTool
from .tools.patch_file import PatchFileTool
from .tools.replace_lines import ReplaceLinesTool
from .tools.replace_symbol import ReplaceSymbolTool
from .tools.run_command import RunCommandTool
from .tools.run_tests import RunTestsTool
from .tools.complete_plan_step import CompletePlanStepTool
from .tools.replan import ReplanTool
from .tools.git_status import GitStatusTool
from .tools.git_diff import GitDiffTool


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


def main():

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
    # Execution / Validation
    # =========================================================

    registry.register(
        RunCommandTool(
            workspace
        )
    )

    registry.register(
        RunTestsTool(
            workspace
        )
    )

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
    #
    # IMPORTANT:
    # Register AFTER trace attachment so callback tools receive
    # the traced plan/replan methods.
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

        if user_input.lower() in {
            "exit",
            "quit",
        }:

            break

        if not user_input:

            continue

        result = (
            agent.run(
                user_input,
                use_planning=True,
            )
        )

        print(
            f"\nMiniCodex >\n"
            f"{result}"
        )

        # =====================================================
        # Trace Summary
        # =====================================================

        trace_summary = (
            trace_recorder
            .summary()
        )

        print(
            "\n[Trace Summary]"
        )

        print(
            "Task ID: "
            f"{trace_summary.task_id}"
        )

        print(
            "Events: "
            f"{trace_summary.total_events}"
        )

        print(
            "LLM Calls: "
            f"{trace_summary.llm_calls}"
        )

        print(
            "Tool Calls: "
            f"{trace_summary.tool_calls}"
        )

        print(
            "Edits: "
            f"{trace_summary.edits}"
        )

        print(
            "Validation Runs: "
            f"{trace_summary.validation_runs}"
        )

        print(
            "Rollbacks: "
            f"{trace_summary.rollbacks}"
        )

        print(
            "Replans: "
            f"{trace_summary.replans}"
        )

        print(
            "Safety Blocks: "
            f"{trace_summary.safety_blocks}"
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

    main()