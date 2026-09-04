from pathlib import Path

from dotenv import load_dotenv

from .agent.agent import MiniCodexAgent
from .agent.planner import Planner
from .agent.replanner import Replanner
from .llm.client import LLMClient

from .tools.registry import ToolRegistry
from .tools.read_file import ReadFileTool
from .tools.list_files import ListFilesTool
from .tools.write_file import WriteFileTool
from .tools.search_code import SearchCodeTool
from .tools.patch_file import PatchFileTool
from .tools.run_command import RunCommandTool
from .tools.run_tests import RunTestsTool
from .tools.complete_plan_step import CompletePlanStepTool
from .tools.replan import ReplanTool


PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


def main():

    workspace = PROJECT_ROOT

    # =========================
    # LLM
    # =========================

    llm = LLMClient()

    # =========================
    # Tool Registry
    # =========================

    registry = ToolRegistry()

    registry.register(
        ListFilesTool(workspace)
    )

    registry.register(
        ReadFileTool(workspace)
    )

    registry.register(
        SearchCodeTool(workspace)
    )

    registry.register(
        WriteFileTool(workspace)
    )

    registry.register(
        PatchFileTool(workspace)
    )

    registry.register(
        RunCommandTool(workspace)
    )

    registry.register(
        RunTestsTool(workspace)
    )

    replanner = Replanner(
        llm=llm
    )

    # =========================
    # Planner
    # =========================

    planner = Planner(
        llm=llm
    )

    # =========================
    # Agent
    # =========================

    agent = MiniCodexAgent(
        llm=llm,
        registry=registry,
        planner=planner,
        replanner=replanner,
        max_steps=20
    )

    # 必须 Agent 创建以后才能注册
    # 因为 Tool 需要 agent callback

    registry.register(
        CompletePlanStepTool(
            callback=agent.complete_plan_step
        )
    )

    registry.register(
        ReplanTool(
            callback=agent.replan
        )
    )

    # =========================
    # CLI Loop
    # =========================

    while True:

        user_input = input(
            "\nYou > "
        ).strip()

        if user_input.lower() in {
            "exit",
            "quit"
        }:
            break

        if not user_input:
            continue

        result = agent.run(
            user_input,
            use_planning=True
        )

        print(
            f"\nMiniCodex >\n{result}"
        )


if __name__ == "__main__":
    main()
