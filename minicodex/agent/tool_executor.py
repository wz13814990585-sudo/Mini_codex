from dataclasses import dataclass

from ..tools.results import ToolResult


@dataclass
class ToolExecution:
    tool_name: str
    arguments: dict
    result: ToolResult