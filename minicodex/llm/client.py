import os

from openai import OpenAI


class LLMClient:

    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com"
        )

        self.model = os.getenv(
            "DEEPSEEK_MODEL",
            "deepseek-chat"
        )

    def chat(
        self,
        messages: list,
        tools: list | None = None
    ):
        kwargs = {
            "model": self.model,
            "messages": messages,
        }

        if tools:
            kwargs["tools"] = tools

        response = self.client.chat.completions.create(
            **kwargs
        )

        return response.choices[0].message