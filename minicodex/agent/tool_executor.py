"""Reliable tool execution boundary."""

import json

from dataclasses import dataclass

from ..tools.results import ToolResult


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


class ToolExecutor:
    """
    Execute tools reliably.

    Responsibilities:
    - Parse raw LLM tool arguments.
    - Validate the basic argument shape.
    - Dispatch through ToolRegistry.
    - Convert execution exceptions into ToolResult.
    - Enforce the ToolResult return contract.

    It intentionally does NOT decide:
    - whether a call is a harmful duplicate,
    - whether validation is sufficient,
    - whether the agent should recover or replan,
    - whether a plan step is complete.

    Those are orchestration policies owned by the agent loop
    and its controllers.
    """

    def __init__(
        self,
        registry,
    ):
        self.registry = registry

    # =========================================================
    # Prepare
    # =========================================================

    def prepare(
        self,
        tool_name: str,
        raw_arguments: str,
    ) -> PreparedToolCall:
        """
        Parse raw JSON arguments from an LLM tool call.

        This method does not execute the tool.
        """

        try:
            arguments = json.loads(
                raw_arguments
            )

        except Exception as e:
            return PreparedToolCall(
                tool_name=tool_name,
                arguments={},
                error=ToolResult(
                    success=False,
                    summary=(
                        f"Could not parse arguments "
                        f"for tool '{tool_name}'."
                    ),
                    data={
                        "tool_name": tool_name,
                        "failure_type": (
                            "argument_parsing"
                        ),
                    },
                    error=(
                        f"{type(e).__name__}: {e}"
                    ),
                ),
            )

        # Tool arguments must be a JSON object because
        # ToolRegistry ultimately calls:
        #
        #     tool.execute(**arguments)
        #
        # Lists, strings, numbers, and null are therefore
        # invalid argument containers.
        if not isinstance(
            arguments,
            dict,
        ):
            return PreparedToolCall(
                tool_name=tool_name,
                arguments={},
                error=ToolResult(
                    success=False,
                    summary=(
                        f"Arguments for tool "
                        f"'{tool_name}' must be "
                        "a JSON object."
                    ),
                    data={
                        "tool_name": tool_name,
                        "failure_type": (
                            "invalid_argument_shape"
                        ),
                        "received_type": (
                            type(arguments).__name__
                        ),
                    },
                    error=(
                        "Tool arguments must decode "
                        "to a dictionary."
                    ),
                ),
            )

        return PreparedToolCall(
            tool_name=tool_name,
            arguments=arguments,
        )

    # =========================================================
    # Execute Prepared Tool Call
    # =========================================================

    def execute_prepared(
        self,
        prepared: PreparedToolCall,
    ) -> ToolExecution:
        """
        Execute an already prepared tool call.

        This is the reliable execution boundary:
        exceptions and invalid tool return values are converted
        into ToolResult instead of escaping into AgentLoop.
        """

        # Defensive behaviour:
        # execute_prepared() is safe even if the caller passes
        # a preparation that already failed.
        if prepared.error is not None:
            return ToolExecution(
                tool_name=prepared.tool_name,
                arguments=prepared.arguments,
                result=prepared.error,
            )

        try:
            result = self.registry.execute(
                prepared.tool_name,
                prepared.arguments,
            )

        except Exception as e:
            result = ToolResult(
                success=False,
                summary=(
                    f"Tool '{prepared.tool_name}' "
                    "failed during execution."
                ),
                data={
                    "tool_name": (
                        prepared.tool_name
                    ),
                    "failure_type": "execution",
                },
                error=(
                    f"{type(e).__name__}: {e}"
                ),
            )

        # Every tool must obey the ToolResult contract.
        if not isinstance(
            result,
            ToolResult,
        ):
            invalid_result = result

            result = ToolResult(
                success=False,
                summary=(
                    f"Tool '{prepared.tool_name}' "
                    "returned an invalid result type."
                ),
                data={
                    "tool_name": (
                        prepared.tool_name
                    ),
                    "failure_type": (
                        "invalid_result_type"
                    ),
                    "returned_type": (
                        type(
                            invalid_result
                        ).__name__
                    ),
                },
                error=(
                    "Every tool must return "
                    "ToolResult."
                ),
            )

        return ToolExecution(
            tool_name=prepared.tool_name,
            arguments=prepared.arguments,
            result=result,
        )