from pathlib import Path

from dotenv import load_dotenv

from .agent.agent import MiniCodexAgent
from .agent.planner import Planner
from .agent.replanner import Replanner
from .agent.repo_map import RepoMap
from .agent.symbol_index import SymbolIndex

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
    # Read / Navigation Tools
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
    # Replanner
    # =========================================================

    replanner = (
        Replanner(
            llm=llm
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
    # CLI Loop
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


if __name__ == "__main__":

    main()