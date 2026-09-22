"""CLI composition root for an arbitrary local coding workspace."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from openai import OpenAIError

from . import __version__
from .agent.agent import MiniCodexAgent
from .agent.context import RepoMap, SymbolIndex
from .agent.memory import LongTermMemoryStore, attach_long_term_memory
from .agent.observability import TraceRecorder, attach_runtime_tracing
from .agent.planning import Planner, Replanner, RequirementsExtractor
from .agent.routing import TaskRouter
from .agent.safety import SandboxLimits, SandboxRunner
from .agent.validation import SemanticRegressionJudge
from .doctor import diagnose
from .llm import LLMClient, ModelConfig, ModelConfigurationError
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


def build_agent(config: WorkspaceConfig, *, llm=None, control_llm=None, judge_llm=None,
                model_config: ModelConfig | None = None,
                output_level="normal") -> tuple[MiniCodexAgent, TraceRecorder, LongTermMemoryStore]:
    """Construct one Harness whose filesystem tools target ``workspace_root``."""
    workspace = config.workspace_root
    llm = llm or LLMClient(config=model_config)
    control_model = os.getenv("DEEPSEEK_CONTROL_MODEL", "").strip()
    judge_model = os.getenv("DEEPSEEK_JUDGE_MODEL", "").strip()
    control_llm = control_llm or (
        LLMClient(config=(model_config or ModelConfig.from_environment()).with_model(control_model))
        if control_model else llm
    )
    judge_llm = judge_llm or (
        LLMClient(config=(model_config or ModelConfig.from_environment()).with_model(judge_model))
        if judge_model else control_llm
    )
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


def run_interactive(config: WorkspaceConfig, *, model_config: ModelConfig | None = None,
                    output_level="normal") -> None:
    agent, recorder, _memory = build_agent(
        config, model_config=model_config, output_level=output_level,
    )
    if output_level in {"verbose", "debug"}:
        print(f"[MiniCodex workspace] {config.workspace_root}")
    while True:
        try:
            user_input = input("\n你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if user_input.lower() in {"exit", "quit"}:
            return
        if not user_input:
            continue
        try:
            result = agent.run(user_input)
        finally:
            config.trace_root.mkdir(parents=True, exist_ok=True)
            recorder.save_jsonl(config.trace_root / "latest.jsonl")
        print(f"\nMiniCodex >\n{result}")


def run_once(config: WorkspaceConfig, prompt: str, *, model_config: ModelConfig | None = None,
             output_level="normal") -> str:
    """Run one automation-friendly task and persist its trace even on failure."""
    if not prompt.strip():
        raise ValueError("单任务 prompt 不能为空")
    agent, recorder, _memory = build_agent(
        config, model_config=model_config, output_level=output_level,
    )
    try:
        return agent.run(prompt.strip())
    finally:
        config.trace_root.mkdir(parents=True, exist_ok=True)
        recorder.save_jsonl(config.trace_root / "latest.jsonl")


def _add_runtime_options(parser: argparse.ArgumentParser, *, preserve_parent=False) -> None:
    inherited = argparse.SUPPRESS if preserve_parent else None
    parser.add_argument("--workspace", "-w", metavar="PATH",
                        default=inherited,
                        help="要检查与编辑的仓库（默认：当前目录）")
    parser.add_argument("--output", choices=("normal", "verbose", "debug"),
                        default=argparse.SUPPRESS if preserve_parent else "normal",
                        help="输出详细程度：normal / verbose / debug")
    parser.add_argument("--model", default=inherited,
                        help="覆盖 MINICODEX_MODEL / DEEPSEEK_MODEL")
    parser.add_argument("--base-url", default=inherited,
                        help="覆盖 MINICODEX_BASE_URL / DEEPSEEK_BASE_URL")
    parser.add_argument("--api-key-env", metavar="NAME",
                        default=inherited,
                        help="从指定环境变量读取 API Key")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="minicodex",
        description="面向本地代码仓库的自主编程助手",
    )
    parser.add_argument("--version", action="version", version=f"MiniCodex {__version__}")
    # Keep the 0.1 command shape working for scripts while presenting explicit
    # product commands to new users.
    _add_runtime_options(parser)
    parser.add_argument("--prompt", help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    run = commands.add_parser("run", help="执行一个编码任务后退出")
    run.add_argument("task", help="要执行的自然语言任务")
    _add_runtime_options(run, preserve_parent=True)

    chat = commands.add_parser("chat", help="启动交互式编码会话")
    _add_runtime_options(chat, preserve_parent=True)

    ui = commands.add_parser("ui", help="启动本地 MiniCodex Web 工作台")
    _add_runtime_options(ui, preserve_parent=True)
    ui.add_argument("--port", type=int, default=8765,
                    help="本地 UI 端口（默认：8765；使用 0 自动分配）")
    ui.add_argument("--no-browser", action="store_true",
                    help="启动服务但不自动打开浏览器")

    doctor = commands.add_parser("doctor", help="检查本机环境与模型配置")
    doctor.add_argument("--workspace", "-w", metavar="PATH",
                        default=argparse.SUPPRESS,
                        help="要检查的工作区（默认：当前目录）")
    doctor.add_argument("--model", default=argparse.SUPPRESS,
                        help="覆盖配置的模型名称")
    doctor.add_argument("--base-url", default=argparse.SUPPRESS,
                        help="覆盖配置的模型地址")
    doctor.add_argument("--api-key-env", metavar="NAME",
                        default=argparse.SUPPRESS,
                        help="从指定环境变量读取 API Key")
    doctor.add_argument("--connect", action="store_true",
                        help="发送一次最小请求验证模型连接（可能产生少量费用）")
    doctor.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    return parser


def _load_cli_environment() -> None:
    """Load only the launch directory's .env; never scan arbitrary parents."""

    candidate = Path.cwd() / ".env"
    if candidate.is_file():
        load_dotenv(candidate, override=False)


def _model_config(args: argparse.Namespace) -> ModelConfig:
    return ModelConfig.from_environment(
        api_key_env=getattr(args, "api_key_env", None),
        base_url=getattr(args, "base_url", None),
        model=getattr(args, "model", None),
    )


def _print_configuration_error(exc: ModelConfigurationError) -> None:
    print(f"配置错误：{exc}", file=sys.stderr)
    print("请运行 `minicodex doctor` 查看修复建议。", file=sys.stderr)


def main(argv=None) -> int:
    _load_cli_environment()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = WorkspaceConfig.create(args.workspace, application_root=APPLICATION_ROOT)
    except ValueError as exc:
        parser.error(str(exc))

    model_config = _model_config(args)
    if args.command == "doctor":
        report = diagnose(config, model_config, connect=args.connect)
        print(report.render_json() if args.json else report.render())
        return 0 if report.ready else 1

    if args.command == "ui":
        from .ui import run_ui

        try:
            run_ui(
                config,
                model_config,
                port=args.port,
                output_level=args.output,
                open_browser=not args.no_browser,
            )
        except KeyboardInterrupt:
            print("\nMiniCodex UI 已停止。", file=sys.stderr)
            return 130
        except OSError as exc:
            print(f"无法启动 MiniCodex UI：{exc}", file=sys.stderr)
            return 4
        return 0

    prompt = args.task if args.command == "run" else args.prompt
    try:
        model_config.require_ready()
    except ModelConfigurationError as exc:
        _print_configuration_error(exc)
        return 2

    if prompt is not None:
        try:
            print(run_once(
                config,
                prompt,
                model_config=model_config,
                output_level=args.output,
            ))
        except ValueError as exc:
            parser.error(str(exc))
        except OpenAIError as exc:
            print(f"模型服务错误：{type(exc).__name__}。请运行 `minicodex doctor --connect`。",
                  file=sys.stderr)
            return 3
        if args.output in {"verbose", "debug"}:
            print(f"\n运行记录：{config.trace_root / 'latest.jsonl'}")
        return 0
    try:
        run_interactive(config, model_config=model_config, output_level=args.output)
    except KeyboardInterrupt:
        print("\n任务已取消；已保留当前工作区和可用运行记录。", file=sys.stderr)
        return 130
    except OpenAIError as exc:
        print(f"模型服务错误：{type(exc).__name__}。请运行 `minicodex doctor --connect`。",
              file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
