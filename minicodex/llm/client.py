from openai import OpenAI

from .config import ModelConfig
from .types import (
    LLMResponse,
    TokenUsage,
)


class LLMClient:

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, temperature: float | None = None,
                 config: ModelConfig | None = None):
        resolved = (config or ModelConfig.from_environment(
            api_key=api_key,
            base_url=base_url,
            model=model,
        )).require_ready()
        self.client = OpenAI(
            api_key=resolved.api_key,
            base_url=resolved.base_url,
        )

        self.config = resolved
        self.model = resolved.model
        self.temperature = temperature

    def chat(
        self,
        messages: list,
        tools: list | None = None,
    ) -> LLMResponse:

        kwargs = {
            "model": self.model,
            "messages": messages,
        }

        if tools:
            kwargs["tools"] = tools
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature

        response = (
            self.client
            .chat
            .completions
            .create(
                **kwargs
            )
        )

        message = (
            response
            .choices[0]
            .message
        )

        usage = (
            response.usage
        )

        token_usage = TokenUsage(
            prompt_tokens=(
                getattr(
                    usage,
                    "prompt_tokens",
                    0,
                )
                if usage
                else 0
            ),
            completion_tokens=(
                getattr(
                    usage,
                    "completion_tokens",
                    0,
                )
                if usage
                else 0
            ),
            total_tokens=(
                getattr(
                    usage,
                    "total_tokens",
                    0,
                )
                if usage
                else 0
            ),
        )

        return LLMResponse(
            message=message,
            usage=token_usage,
        )
