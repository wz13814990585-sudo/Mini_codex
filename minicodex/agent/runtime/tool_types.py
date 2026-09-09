"""Shared data contracts for prepared and completed tool calls."""

from dataclasses import dataclass

from ...tools.results import ToolResult


@dataclass
class PreparedToolCall:
    """A tool call whose arguments have been parsed."""

    tool_name: str
    arguments: dict
    error: ToolResult | None = None


@dataclass
class ToolExecution:
    """Final result of one tool execution."""

    tool_name: str
    arguments: dict
    result: ToolResult
