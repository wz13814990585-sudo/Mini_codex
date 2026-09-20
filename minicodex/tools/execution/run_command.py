from pathlib import Path

from ...agent.safety import (
    SandboxLimits,
    SandboxRunner,
)

from ..base import BaseTool
from ..results import ToolResult


class RunCommandTool(
    BaseTool
):

    name = (
        "run_command"
    )
    capabilities = frozenset({"process.run"})

    description = (
        "通过 MiniCodex 进程沙箱在当前项目工作区执行 shell 命令，"
        "返回标准输出、标准错误、退出码以及沙箱元数据。"
        "仅当命令直接检查用户请求的行为时，才设置 purpose='acceptance'。"
        "不要用此工具运行 pytest；请改用 run_tests。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "要执行的 shell 命令，"
                    "例如 "
                    "'python calculator.py'。"
                ),
            },
            "purpose": {
                "type": "string",
                "enum": [
                    "diagnostic",
                    "acceptance",
                    "regression",
                ],
                "description": (
                    "命令意图。默认为 diagnostic；"
                    "acceptance 结果会登记为定向验证证据。"
                ),
            },
        },
        "required": [
            "command",
        ],
    }

    def __init__(
        self,
        workspace: str = ".",
        timeout: int = 30,
        sandbox: (
            SandboxRunner
            | None
        ) = None,
    ):

        self.workspace = (
            Path(
                workspace
            )
            .resolve()
        )

        self.timeout = max(
            1,
            int(
                timeout
            ),
        )

        self.sandbox = (
            sandbox
            or SandboxRunner(
                workspace=(
                    self.workspace
                ),
                limits=(
                    SandboxLimits(
                        timeout_seconds=(
                            self.timeout
                        )
                    )
                ),
            )
        )

    # =========================================================
    # Execute
    # =========================================================

    def execute(
        self,
        command: str,
        purpose: str = "diagnostic",
    ) -> ToolResult:

        normalized_purpose = str(
            purpose
        ).strip().lower()

        if normalized_purpose not in {
            "diagnostic",
            "acceptance",
            "regression",
        }:
            raise ValueError(
                "purpose 必须为 "
                "'diagnostic'、'acceptance' 或 'regression'。"
            )

        sandbox_result = (
            self.sandbox
            .run_shell(
                command,
                timeout_seconds=(
                    self.timeout
                ),
            )
        )

        # =====================================================
        # Sandbox Could Not Start
        # =====================================================

        if not (
            sandbox_result.started
        ):

            return ToolResult(
                success=False,
                summary=(
                    "无法在进程沙箱中启动命令。"
                ),
                data={
                    "command": (
                        command
                    ),
                    "purpose": normalized_purpose,
                    "exit_code": None,
                    "command_succeeded": (
                        False
                    ),
                    "stdout": "",
                    "stderr": "",
                    "timed_out": (
                        False
                    ),
                    "sandbox": (
                        sandbox_result
                        .sandbox_metadata()
                    ),
                    "failure_type": (
                        sandbox_result
                        .failure_type
                        or "sandbox_start"
                    ),
                },
                error=(
                    sandbox_result.error
                    or (
                        "沙箱进程无法启动。"
                    )
                ),
            )

        # =====================================================
        # Timeout
        # =====================================================

        if (
            sandbox_result
            .timed_out
        ):

            return ToolResult(
                success=False,
                summary=(
                    f"命令在沙箱中超时"
                    f"（{self.timeout} 秒）。"
                ),
                data={
                    "command": (
                        command
                    ),
                    "purpose": normalized_purpose,
                    "exit_code": (
                        sandbox_result
                        .exit_code
                    ),
                    "command_succeeded": (
                        False
                    ),
                    "stdout": (
                        sandbox_result
                        .stdout
                    ),
                    "stderr": (
                        sandbox_result
                        .stderr
                    ),
                    "timed_out": True,
                    "output_truncated": (
                        sandbox_result
                        .output_limited
                    ),
                    "timeout": (
                        self.timeout
                    ),
                    "sandbox": (
                        sandbox_result
                        .sandbox_metadata()
                    ),
                    "failure_type": (
                        "sandbox_timeout"
                    ),
                },
                error=(
                    "命令执行超时。"
                ),
            )

        stdout = (
            sandbox_result
            .stdout
            or ""
        )

        stderr = (
            sandbox_result
            .stderr
            or ""
        )

        command_succeeded = (
            sandbox_result
            .command_succeeded
        )

        exit_code = (
            sandbox_result
            .exit_code
        )

        # =====================================================
        # Summary
        # =====================================================

        if (
            command_succeeded
        ):

            summary = (
                "命令在沙箱中成功完成，"
                f"退出码为 {exit_code}。"
            )

        else:

            summary = (
                "命令在沙箱中已结束，"
                f"退出码为 {exit_code}。"
            )

        if (
            sandbox_result
            .output_limited
        ):

            summary += (
                " 沙箱截断了捕获的输出。"
            )

        # =====================================================
        # LLM Observation
        # =====================================================

        llm_parts = [
            (
                "退出码："
                f"{exit_code}"
            )
        ]

        if (
            sandbox_result
            .output_limited
        ):

            llm_parts.append(
                (
                    "沙箱说明：捕获的输出已被截断。"
                )
            )

        if (
            stdout.strip()
        ):

            llm_parts.append(
                (
                    "标准输出：\n"
                    + stdout
                )
            )

        if (
            stderr.strip()
        ):

            llm_parts.append(
                (
                    "标准错误：\n"
                    + stderr
                )
            )

        llm_content = "\n".join(
            llm_parts
        )

        return ToolResult(
            success=True,
            summary=(
                summary
            ),
            data={
                "command": (
                    command
                ),
                "purpose": normalized_purpose,
                "exit_code": (
                    exit_code
                ),
                "command_succeeded": (
                    command_succeeded
                ),
                "stdout": (
                    stdout
                ),
                "stderr": (
                    stderr
                ),
                "timed_out": False,
                "output_truncated": (
                    sandbox_result
                    .output_limited
                ),
                "sandbox": (
                    sandbox_result
                    .sandbox_metadata()
                ),
            },
            llm_content=(
                llm_content
            ),
        )
