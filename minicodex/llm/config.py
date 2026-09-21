"""Provider-neutral model configuration for the MiniCodex product shell."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import os
from urllib.parse import urlparse


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class ModelConfigurationError(ValueError):
    """Raised before a provider call when model configuration is incomplete."""


@dataclass(frozen=True)
class ModelConfig:
    """Resolved OpenAI-compatible provider settings without exposing secrets."""

    api_key: str | None = field(repr=False)
    base_url: str
    model: str
    api_key_source: str | None = None

    @classmethod
    def from_environment(
        cls,
        *,
        api_key: str | None = None,
        api_key_env: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> "ModelConfig":
        key = (api_key or "").strip() or None
        source = "explicit" if key else None
        if not key and api_key_env:
            key = os.getenv(api_key_env, "").strip() or None
            source = api_key_env if key else None
        if not key and not api_key_env:
            for name in ("MINICODEX_API_KEY", "DEEPSEEK_API_KEY"):
                key = os.getenv(name, "").strip() or None
                if key:
                    source = name
                    break
        resolved_url = (
            (base_url or "").strip()
            or os.getenv("MINICODEX_BASE_URL", "").strip()
            or os.getenv("DEEPSEEK_BASE_URL", "").strip()
            or DEFAULT_BASE_URL
        )
        resolved_model = (
            (model or "").strip()
            or os.getenv("MINICODEX_MODEL", "").strip()
            or os.getenv("DEEPSEEK_MODEL", "").strip()
            or DEFAULT_MODEL
        )
        return cls(key, resolved_url.rstrip("/"), resolved_model, source)

    @property
    def configured(self) -> bool:
        return not self.problems()

    def problems(self) -> tuple[str, ...]:
        problems: list[str] = []
        if not self.api_key:
            problems.append(
                "未找到 API Key；请设置 MINICODEX_API_KEY 或 DEEPSEEK_API_KEY"
            )
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            problems.append("模型 Base URL 必须是有效的 http(s) 地址")
        if not self.model:
            problems.append("模型名称不能为空")
        return tuple(problems)

    def require_ready(self) -> "ModelConfig":
        problems = self.problems()
        if problems:
            raise ModelConfigurationError("；".join(problems))
        return self

    def with_model(self, model: str | None) -> "ModelConfig":
        return replace(self, model=(model or self.model).strip())
