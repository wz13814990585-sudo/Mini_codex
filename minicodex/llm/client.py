import os

from openai import OpenAI

from .types import (
    LLMResponse,
    TokenUsage,
)


class LLMClient:

    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv(
                "DEEPSEEK_API_KEY"
            ),
            base_url=(
                "https://api.deepseek.com"
            ),
        )

        self.model = os.getenv(
            "DEEPSEEK_MODEL",
            "deepseek-chat",
        )

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