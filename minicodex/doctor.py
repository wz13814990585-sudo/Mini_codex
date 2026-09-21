"""Local readiness diagnostics for the MiniCodex CLI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib.util
import json
import shutil
import sys

from .llm import LLMClient, ModelConfig
from .workspace import WorkspaceConfig


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    passed: bool
    detail: str
    required: bool = True


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.passed for check in self.checks if check.required)

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "checks": [asdict(check) for check in self.checks],
        }

    def render(self) -> str:
        rows = ["MiniCodex 环境诊断", ""]
        for check in self.checks:
            status = "通过" if check.passed else ("可选" if not check.required else "失败")
            rows.append(f"{check.name:<18} {status:<4} {check.detail}")
        rows.extend(("", f"就绪 = {'true' if self.ready else 'false'}"))
        return "\n".join(rows)

    def render_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def diagnose(
    workspace: WorkspaceConfig,
    model: ModelConfig,
    *,
    connect: bool = False,
) -> DoctorReport:
    """Inspect local prerequisites and optionally make one minimal provider call."""

    checks = [
        DoctorCheck(
            "python",
            sys.version_info >= (3, 11),
            f"{sys.executable} ({sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})",
        ),
        DoctorCheck("workspace", True, str(workspace.workspace_root)),
        DoctorCheck(
            "git",
            shutil.which("git") is not None,
            shutil.which("git") or "未安装；代码修改仍可运行，但缺少差异与状态能力",
            required=False,
        ),
        DoctorCheck(
            "api_key",
            bool(model.api_key),
            f"已从 {model.api_key_source} 读取（不会显示密钥）"
            if model.api_key else "设置 MINICODEX_API_KEY 或 DEEPSEEK_API_KEY",
        ),
        DoctorCheck(
            "base_url",
            not any("Base URL" in problem for problem in model.problems()),
            model.base_url,
        ),
        DoctorCheck("model", bool(model.model), model.model or "未配置"),
        DoctorCheck(
            "browser_validation",
            importlib.util.find_spec("playwright") is not None,
            "Playwright 可用" if importlib.util.find_spec("playwright") else "未安装 Playwright（可选）",
            required=False,
        ),
    ]
    if connect:
        if model.configured:
            try:
                response = LLMClient(config=model, temperature=0).chat([
                    {"role": "system", "content": "Reply with OK only."},
                    {"role": "user", "content": "health check"},
                ])
                content = str(getattr(response.message, "content", "") or "").strip()
                checks.append(DoctorCheck("provider_connection", bool(content),
                                          f"已连接 {model.model}" if content else "模型返回为空"))
            except Exception as exc:  # Provider SDK exceptions vary by backend.
                checks.append(DoctorCheck("provider_connection", False,
                                          _safe_provider_error(exc)))
        else:
            checks.append(DoctorCheck("provider_connection", False, "模型配置不完整，未发起连接"))
    return DoctorReport(tuple(checks))


def _safe_provider_error(exc: Exception) -> str:
    name = type(exc).__name__
    if "Authentication" in name:
        return "认证失败，请检查 API Key"
    if "RateLimit" in name:
        return "服务限流或额度不足"
    if "Timeout" in name:
        return "连接超时"
    if "Connection" in name:
        return "无法连接模型服务"
    return f"模型连接失败（{name}）"
