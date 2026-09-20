import re
import sys
from hashlib import sha1
from pathlib import Path

from ...agent.safety import (
    SandboxLimits,
    SandboxRunner,
)

from ..base import BaseTool
from ..results import ToolResult
from ...agent.validation import TestTargetResolver
from ...agent.context.project_execution_environment import ProjectExecutionEnvironment


MAX_FAILURE_DETAIL_LINES = 40

MAX_FAILED_TEST_NAMES = 20


VALID_PURPOSES = {
    "acceptance",
    "regression",
}


class RunTestsTool(
    BaseTool
):

    name = (
        "run_tests"
    )
    capabilities = frozenset({"test.run"})

    description = (
        "在 MiniCodex 进程沙箱中使用 pytest 运行 Python 测试，"
        "并返回结构化验证证据。"
        "使用 purpose='acceptance' 运行能证明用户请求行为的特定测试；"
        "使用 purpose='regression' 做既有或全量回归验证。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "测试路径，例如 "
                    "'minicodex/tests/test_example.py'。"
                    "使用 '.' 表示完整回归套件。"
                ),
            },
            "purpose": {
                "type": "string",
                "enum": [
                    "acceptance",
                    "regression",
                ],
                "description": (
                    "'acceptance' 用于证明"
                    "用户请求的具体行为；"
                    "'regression' 用于检查既有行为。"
                ),
            },
        },
        "required": [],
    }

    def __init__(
        self,
        workspace: str = ".",
        timeout: int = 60,
        sandbox: (
            SandboxRunner
            | None
        ) = None,
        python_executable: str | None = None,
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
        self.environment = ProjectExecutionEnvironment.discover(self.workspace)
        self.python_executable = str(python_executable or self.environment.python_executable)
        if python_executable:
            self.environment = ProjectExecutionEnvironment(self.workspace, self.python_executable,
                self.environment.package_manager, (self.python_executable,), (self.python_executable, "-m", "pytest"), True)

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
        path: str = ".",
        purpose: str = "regression",
    ) -> ToolResult:

        normalized_path = (
            str(
                path
            )
            .strip()
        )

        normalized_purpose = (
            str(
                purpose
            )
            .strip()
            .lower()
        )

        # =====================================================
        # Purpose Validation
        # =====================================================

        if (
            normalized_purpose
            not in VALID_PURPOSES
        ):

            raise ValueError(
                (
                    "purpose 必须为 "
                    "'acceptance' 或 "
                    "'regression'。"
                )
            )

        # =====================================================
        # Acceptance Must Be Targeted
        # =====================================================

        if (
            normalized_purpose
            == "acceptance"
            and normalized_path
            in {
                "",
                ".",
                "./",
            }
        ):

            raise ValueError(
                (
                    "验收验证必须指向具体的测试路径。"
                    "完整测试套件本身不能作为验收证据。"
                )
            )

        if (
            normalized_purpose == "acceptance"
            and not TestTargetResolver.is_test_path(normalized_path)
        ):
            raise ValueError(
                "验收验证必须指向实际的测试文件或 "
                "pytest node id；源码模块不能作为验收证据。"
            )

        if not (
            normalized_path
        ):

            normalized_path = (
                "."
            )

        # =====================================================
        # Workspace Guard
        # =====================================================

        normalized_path = (
            self._normalize_test_path(
                normalized_path
            )
        )

        # =====================================================
        # pytest argv
        # =====================================================

        if not self.environment.command_available:
            return ToolResult(success=False, summary="项目测试环境不可用。", data={
                "path": normalized_path, "purpose": normalized_purpose, "outcome": "inconclusive",
                "failure_type": "environment_unavailable", "environment": self.environment.summary(),
            }, error="检测到的项目命令未安装。")
        command = [
            *self.environment.pytest_argv(),
            "-p",
            "no:debugging",
            normalized_path,
            "-q",
        ]

        sandbox_result = (
            self.sandbox
            .run_argv(
                command,
                timeout_seconds=(
                    self.timeout
                ),
            )
        )

        # =====================================================
        # Sandbox Start Failure
        # =====================================================

        if not (
            sandbox_result.started
        ):

            return ToolResult(
                success=False,
                summary=(
                    "无法在进程沙箱中启动测试。"
                ),
                data={
                    "path": (
                        normalized_path
                    ),
                    "purpose": (
                        normalized_purpose
                    ),
                    "timed_out": False,
                    "sandbox": (
                        sandbox_result
                        .sandbox_metadata()
                    ),
                    "failure_type": (
                        sandbox_result
                        .failure_type
                        or "sandbox_start"
                    ),
                    "outcome": "inconclusive",
                    "failed_count": None,
                    "validation_summary": "无法启动测试。",
                },
                error=(
                    sandbox_result.error
                    or (
                        "沙箱 pytest "
                        "进程无法启动。"
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
                    f"测试在沙箱中超时"
                    f"（{self.timeout} 秒）。"
                ),
                data={
                    "path": (
                        normalized_path
                    ),
                    "purpose": (
                        normalized_purpose
                    ),
                    "timeout": (
                        self.timeout
                    ),
                    "timed_out": True,
                    "output_truncated": (
                        sandbox_result
                        .output_limited
                    ),
                    "sandbox": (
                        sandbox_result
                        .sandbox_metadata()
                    ),
                    "failure_type": (
                        "sandbox_timeout"
                    ),
                    "outcome": "inconclusive",
                    "failed_count": None,
                    "validation_summary": "测试超时。",
                },
                error=(
                    "pytest 执行超时"
                ),
            )

        # =====================================================
        # Parse pytest result
        # =====================================================

        parsed = (
            parse_pytest_output(
                exit_code=(
                    sandbox_result
                    .exit_code
                    if (
                        sandbox_result
                        .exit_code
                        is not None
                    )
                    else -1
                ),
                stdout=(
                    sandbox_result
                    .stdout
                ),
                stderr=(
                    sandbox_result
                    .stderr
                ),
                workspace=self.workspace,
            )
        )

        parsed[
            "output_truncated"
        ] = (
            sandbox_result
            .output_limited
        )

        llm_content = (
            build_pytest_llm_content(
                parsed
            )
        )

        summary = (
            build_pytest_summary(
                parsed
            )
        )

        if (
            sandbox_result
            .output_limited
        ):

            summary += (
                " 沙箱截断了捕获的 pytest 输出。"
            )

        return ToolResult(
            success=True,
            summary=(
                summary
            ),
            data={
                "path": (
                    normalized_path
                ),
                "purpose": (
                    normalized_purpose
                ),
                **parsed,
                "outcome": (
                    "passed" if parsed["tests_passed"] else "failed"
                ),
                "failed_count": parsed["failed"] + parsed["errors"],
                "validation_summary": summary,
                "sandbox": (
                    sandbox_result
                    .sandbox_metadata()
                ),
            },
            llm_content=(
                llm_content
            ),
        )

    # =========================================================
    # Test Path Guard
    # =========================================================

    def _normalize_test_path(
        self,
        path: str,
    ) -> str:

        if (
            path
            in {
                ".",
                "./",
            }
        ):

            return "."

        candidate = (
            (
                self.workspace
                / path
            )
            .resolve()
        )

        try:

            relative = (
                candidate
                .relative_to(
                    self.workspace
                )
            )

        except ValueError:

            raise ValueError(
                (
                    "测试路径必须位于工作区内。"
                )
            )

        return (
            relative
            .as_posix()
        )


# =============================================================
# Parse pytest
# =============================================================


def parse_pytest_output(
    exit_code: int,
    stdout: str,
    stderr: str,
    workspace: str | Path | None = None,
) -> dict:

    passed = (
        _extract_count(
            stdout,
            "passed",
        )
    )

    failed = (
        _extract_count(
            stdout,
            "failed",
        )
    )

    errors = (
        _extract_count(
            stdout,
            "error",
        )
        + _extract_count(
            stdout,
            "errors",
        )
    )

    skipped = (
        _extract_count(
            stdout,
            "skipped",
        )
    )

    xfailed = (
        _extract_count(
            stdout,
            "xfailed",
        )
    )

    xpassed = (
        _extract_count(
            stdout,
            "xpassed",
        )
    )

    failed_tests = (
        _extract_failed_test_names(
            stdout
        )
    )

    failure_details = (
        _failure_detail_lines(
            stdout.splitlines(),
            MAX_FAILURE_DETAIL_LINES,
        )
    )
    failure_fingerprints = tuple(
        sha1(re.sub(r"\b\d+\b", "#", line).strip().encode("utf-8")).hexdigest()[:12]
        for line in failure_details
        if line.strip()
    )[:20]

    stderr_lines = [
        line
        for line
        in stderr.splitlines()
        if line.strip()
    ]

    failure_paths = extract_failure_paths(
        stdout=stdout,
        stderr=stderr,
        workspace=workspace,
    )
    combined_output = f"{stdout}\n{stderr}"
    missing_dependency = re.search(
        r"(?:ModuleNotFoundError:\s*No module named|ImportError:\s*No module named)\s*['\"]([^'\"]+)",
        combined_output,
    )

    return {
        "exit_code": (
            exit_code
        ),
        "passed": (
            passed
        ),
        "failed": (
            failed
        ),
        "errors": (
            errors
        ),
        "skipped": (
            skipped
        ),
        "xfailed": (
            xfailed
        ),
        "xpassed": (
            xpassed
        ),
        "failed_tests": (
            failed_tests
        ),
        "failure_details": (
            failure_details
        ),
        "failure_fingerprints": list(failure_fingerprints),
        "failure_paths": failure_paths,
        "failure_type": "missing_dependency" if missing_dependency else (
            "regression_failed" if exit_code else None
        ),
        "missing_module": missing_dependency.group(1) if missing_dependency else None,
        "stderr": (
            stderr_lines[
                :20
            ]
        ),
        "tests_passed": (
            exit_code
            == 0
        ),
        "timed_out": False,
    }


def extract_failure_paths(
    *,
    stdout: str,
    stderr: str,
    workspace: str | Path | None = None,
) -> list[str]:
    """Conservatively extract repo-local paths from pytest diagnostics."""

    candidates: list[str] = []
    for line in stdout.splitlines():
        if line.startswith("FAILED ") or line.startswith("ERROR "):
            token = line.split(maxsplit=1)[1].split("::", 1)[0].strip()
            candidates.append(token)

    traceback_pattern = re.compile(
        r"(?<![\w.-])((?:[A-Za-z]:)?[\w./\\-]+\.py):\d+(?::\d+)?"
    )
    for text in (stdout, stderr):
        candidates.extend(match.group(1) for match in traceback_pattern.finditer(text))

    root = Path(workspace).resolve() if workspace is not None else None
    normalized: list[str] = []
    for raw in candidates:
        path_text = raw.replace("\\", "/").strip("'\"()[]")
        if not path_text:
            continue
        candidate = Path(path_text)
        if root is not None:
            try:
                resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
                relative = resolved.relative_to(root)
            except (ValueError, OSError):
                continue
            if not resolved.is_file():
                continue
            path_text = relative.as_posix()
        elif candidate.is_absolute() or ".." in candidate.parts:
            continue
        else:
            path_text = candidate.as_posix()
        if path_text not in normalized:
            normalized.append(path_text)
    return normalized


# =============================================================
# Summary
# =============================================================


def build_pytest_summary(
    parsed: dict,
) -> str:

    parts = []

    if (
        parsed[
            "passed"
        ]
    ):

        parts.append(
            (
                f"{parsed['passed']} "
                "通过"
            )
        )

    if (
        parsed[
            "failed"
        ]
    ):

        parts.append(
            (
                f"{parsed['failed']} "
                "失败"
            )
        )

    if (
        parsed[
            "errors"
        ]
    ):

        parts.append(
            (
                f"{parsed['errors']} "
                "错误"
            )
        )

    if (
        parsed[
            "skipped"
        ]
    ):

        parts.append(
            (
                f"{parsed['skipped']} "
                "跳过"
            )
        )

    if not (
        parts
    ):

        parts.append(
            (
                "pytest 退出码为 "
                f"{parsed['exit_code']}"
            )
        )

    return (
        ", ".join(
            parts
        )
        + "."
    )


# =============================================================
# LLM Content
# =============================================================


def build_pytest_llm_content(
    parsed: dict,
) -> str:

    sections = [
        (
            "退出码："
            f"{parsed['exit_code']}"
        )
    ]

    if (
        parsed.get(
            "output_truncated"
        )
    ):

        sections.append(
            (
                "沙箱说明：pytest "
                "输出已被截断。"
            )
        )

    if (
        parsed[
            "failed_tests"
        ]
    ):

        sections.append(
            (
                "失败测试：\n"
                + "\n".join(
                    parsed[
                        "failed_tests"
                    ]
                )
            )
        )

    if (
        parsed[
            "failure_details"
        ]
    ):

        sections.append(
            (
                "详情：\n"
                + "\n".join(
                    parsed[
                        "failure_details"
                    ]
                )
            )
        )

    if (
        parsed[
            "stderr"
        ]
    ):

        sections.append(
            (
                "标准错误：\n"
                + "\n".join(
                    parsed[
                        "stderr"
                    ]
                )
            )
        )

    return "\n".join(
        sections
    )


# =============================================================
# Extract Count
# =============================================================


def _extract_count(
    text: str,
    label: str,
) -> int:

    pattern = (
        rf"(\d+)\s+"
        rf"{re.escape(label)}\b"
    )

    matches = (
        re.findall(
            pattern,
            text,
            re.IGNORECASE,
        )
    )

    if not (
        matches
    ):

        return 0

    return int(
        matches[
            -1
        ]
    )


# =============================================================
# Failed Test Names
# =============================================================


def _extract_failed_test_names(
    stdout: str,
) -> list[str]:

    failed_names = []

    for line in (
        stdout.splitlines()
    ):

        if not (
            line.startswith(
                "FAILED "
            )
        ):

            continue

        failed_names.append(
            line.strip()
        )

        if (
            len(
                failed_names
            )
            >= MAX_FAILED_TEST_NAMES
        ):

            break

    return (
        failed_names
    )


# =============================================================
# Failure Details
# =============================================================


def _failure_detail_lines(
    stdout_lines: list[str],
    max_fail_lines: int,
) -> list[str]:

    detail = []

    capturing = False

    for line in (
        stdout_lines
    ):

        if (
            "FAILURES"
            in line
            or line.startswith(
                "FAILED "
            )
            or line.startswith(
                "E "
            )
            or line.startswith(
                "E\t"
            )
        ):

            capturing = True

        if (
            capturing
        ):

            if (
                re.fullmatch(
                    r"\.+",
                    line.strip(),
                )
            ):

                continue

            detail.append(
                line
            )

            if (
                len(
                    detail
                )
                >= max_fail_lines
            ):

                break

    return (
        detail
    )
