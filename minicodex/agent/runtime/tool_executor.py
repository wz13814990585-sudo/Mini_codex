"""Reliable tool execution boundary."""

import json

from ...tools.results import ToolResult
from ..editing.edit_failure import (
    EditFailureType,
    classify_edit_exception,
    reason_for_edit_failure,
)
from .tool_types import PreparedToolCall, ToolExecution


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

            if raw_arguments is None:
                raw_arguments = "{}"

            if len(raw_arguments) > self.MAX_TOOL_ARGUMENT_CHARS:
                return PreparedToolCall(tool_name=tool_name, arguments={}, error=ToolResult(
                    success=False, summary=f"Arguments for tool '{tool_name}' exceed the size limit.",
                    data={"tool_name": tool_name, "failure_type": "argument_too_large", "max_chars": self.MAX_TOOL_ARGUMENT_CHARS}))

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

        schema_error = self._schema_error(tool_name, arguments)
        if schema_error:
            return PreparedToolCall(tool_name=tool_name, arguments={}, error=ToolResult(
                success=False, summary=f"Arguments for tool '{tool_name}' failed schema validation.",
                data={"tool_name": tool_name, "failure_type": "schema_validation"}, error=schema_error))

        return PreparedToolCall(
            tool_name=tool_name,
            arguments=arguments,
        )

    def _schema_error(self, tool_name, arguments):
        try:
            schema = self.registry.get(tool_name).parameters
        except Exception:
            return None
        properties, required = schema.get("properties", {}), schema.get("required", ())
        missing = [name for name in required if name not in arguments]
        if missing:
            return f"missing required argument(s): {', '.join(missing)}"
        # These Harness-level bindings are accepted by every validator even
        # when a backend tool schema does not repeat them.
        unknown = set(arguments) - set(properties) - {"purpose", "validation_check"}
        # A deliberately empty properties mapping is used by lightweight
        # adapters to mean an open-ended interface.  Preserve that standard
        # JSON-Schema behaviour; production tools declare their accepted
        # fields and therefore remain closed at this boundary.
        is_closed = bool(properties) or schema.get("additionalProperties") is False
        if unknown and is_closed:
            return f"unknown argument(s): {', '.join(sorted(unknown))}"
        for name, value in arguments.items():
            field = properties.get(name, {})
            expected = field.get("type")
            if expected == "string" and not isinstance(value, str): return f"{name} must be a string"
            if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)): return f"{name} must be an integer"
            if expected == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))): return f"{name} must be a number"
            if expected == "array" and not isinstance(value, list): return f"{name} must be an array"
            if expected == "object" and not isinstance(value, dict): return f"{name} must be an object"
            if "enum" in field and value not in field["enum"]: return f"{name} must be one of {field['enum']}"
        return None

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
            edit_failure = classify_edit_exception(prepared.tool_name, e)
            reason_code = reason_for_edit_failure(edit_failure)
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
                    "failure_type": (
                        edit_failure.value
                        if edit_failure != EditFailureType.UNKNOWN
                        else "execution"
                    ),
                    "edit_failure_type": edit_failure.value,
                    "reason_code": getattr(reason_code, "value", None),
                    "path": prepared.arguments.get("path"),
                    "symbol": prepared.arguments.get("symbol"),
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
    MAX_TOOL_ARGUMENT_CHARS = 1_000_000
