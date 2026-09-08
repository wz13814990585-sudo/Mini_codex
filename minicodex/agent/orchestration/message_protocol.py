"""Deterministic provider tool-message protocol enforcement."""

from __future__ import annotations

from collections.abc import Iterable


class ToolMessageProtocolError(RuntimeError):
    """Raised when provider conversation history is structurally invalid."""


def _value(item, name, default=None):
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _tool_call_id(tool_call) -> str:
    value = _value(tool_call, "id")
    return str(value or "").strip()


def validate_tool_message_protocol(
    messages: Iterable,
) -> bool:
    """Assert that every assistant tool-call batch is closed in place.

    A batch is closed only when every declared ``tool_call_id`` has one
    corresponding tool response, with no intervening non-tool message.
    """

    pending_order: list[str] = []
    pending: set[str] = set()
    answered: set[str] = set()

    for index, message in enumerate(messages):
        role = str(_value(message, "role", "") or "")

        if role == "assistant":
            tool_calls = list(_value(message, "tool_calls", []) or [])
            if pending:
                missing = [item for item in pending_order if item in pending]
                raise ToolMessageProtocolError(
                    "Assistant message at index "
                    f"{index} appeared before the open tool-call batch was "
                    f"closed; missing responses: {missing}."
                )
            if not tool_calls:
                continue

            ids = [_tool_call_id(call) for call in tool_calls]
            if any(not item for item in ids):
                raise ToolMessageProtocolError(
                    f"Assistant tool-call batch at index {index} contains "
                    "an empty tool_call_id."
                )
            duplicates = sorted(
                {item for item in ids if ids.count(item) > 1}
            )
            if duplicates:
                raise ToolMessageProtocolError(
                    f"Assistant tool-call batch at index {index} declares "
                    f"duplicate tool_call_ids: {duplicates}."
                )

            pending_order = ids
            pending = set(ids)
            answered = set()
            continue

        if role == "tool":
            tool_call_id = str(
                _value(message, "tool_call_id", "") or ""
            ).strip()
            if not pending_order:
                raise ToolMessageProtocolError(
                    f"Tool response at index {index} has no open assistant "
                    "tool-call batch."
                )
            if tool_call_id not in set(pending_order):
                raise ToolMessageProtocolError(
                    f"Tool response at index {index} references undeclared "
                    f"tool_call_id {tool_call_id!r}."
                )
            if tool_call_id in answered:
                raise ToolMessageProtocolError(
                    f"Tool response for {tool_call_id!r} appears more than "
                    "once in the same batch."
                )

            answered.add(tool_call_id)
            pending.discard(tool_call_id)
            if not pending:
                pending_order = []
                answered = set()
            continue

        if pending:
            missing = [item for item in pending_order if item in pending]
            raise ToolMessageProtocolError(
                f"Non-tool message with role {role!r} at index {index} "
                "interleaves an open assistant tool-call batch; missing "
                f"responses: {missing}."
            )

    if pending:
        missing = [item for item in pending_order if item in pending]
        raise ToolMessageProtocolError(
            "Conversation ends with an open assistant tool-call batch; "
            f"missing responses: {missing}."
        )

    return True


assert_tool_call_batches_closed = validate_tool_message_protocol


def close_tool_batch_before_control_transition(
    messages: list,
    remaining_tool_calls,
    skipped_reason: str,
    followup_user_message: str | None = None,
) -> None:
    """Close the current tool batch before committing a control message."""

    for tool_call in remaining_tool_calls:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": _tool_call_id(tool_call),
                "content": (
                    "Tool call skipped because "
                    f"{skipped_reason}."
                ),
            }
        )

    # This local assertion is deliberately before the user transition.
    validate_tool_message_protocol(messages)

    if followup_user_message:
        messages.append(
            {
                "role": "user",
                "content": followup_user_message,
            }
        )

