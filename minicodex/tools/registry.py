"""Tool registry."""

from .base import BaseTool


class ToolRegistry:

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:

        if tool.name in self._tools:
            raise ValueError(
                f"Tool '{tool.name}' is already registered."
            )

        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:

        tool = self._tools.get(name)

        if tool is None:
            raise ValueError(
                f"Tool '{name}' not found."
            )

        return tool

    def get_schemas(self) -> list[dict]:

        return [
            tool.to_schema()
            for tool in self._tools.values()
        ]

    def execute(
        self,
        name: str,
        arguments: dict
    ):

        tool = self.get(name)

        return tool.execute(**arguments)
