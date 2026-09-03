"""Compact conversation history so old tool payloads are not resent."""

import json
import re


DEFAULT_KEEP_RECENT_ROUNDS = 2
DEFAULT_MAX_TOOL_CHARS = 800


def compact_messages(
    messages: list,
    keep_recent_rounds: int = DEFAULT_KEEP_RECENT_ROUNDS,
    max_tool_chars: int = DEFAULT_MAX_TOOL_CHARS,
) -> list:
    """Fold old tool bodies and bulky write/patch arguments in-place.

    The original user message and the most recent ``keep_recent_rounds``
    assistant/tool rounds are left unchanged.
    """

    if len(messages) < 2:
        return messages

    round_starts = [
        index
        for index, message in enumerate(messages)
        if _has_tool_calls(message)
    ]

    if len(round_starts) <= keep_recent_rounds:
        return messages

    compact_until = round_starts[-keep_recent_rounds]
    id_to_tool = _tool_call_index(messages)

    for index in range(1, compact_until):
        message = messages[index]
        role = message.get("role")

        if role == "tool":
            content = str(message.get("content") or "")
            if len(content) <= max_tool_chars:
                continue
            if content.startswith("[") and " chars" in content:
                continue

            tool_name, arguments = id_to_tool.get(
                message.get("tool_call_id"),
                ("tool", "{}"),
            )
            message["content"] = summarize_tool_result(
                tool_name,
                arguments,
                content,
            )

        elif _has_tool_calls(message):
            omit_tool_call_payloads(message)

    return messages


def summarize_tool_result(
    tool_name: str,
    arguments,
    content: str,
) -> str:
    args = _parse_arguments(arguments)
    path = str(args.get("path") or args.get("command") or "").strip()
    suffix = f" {path}" if path else ""
    failed = _tool_result_failed(content)

    if tool_name == "read_file":
        if failed:
            return f"[read_file]{suffix} FAILED"
        lines = content.count("\n") + (1 if content else 0)
        return f"[read_file]{suffix} ({lines} lines)"

    if tool_name in {"run_tests", "run_command"}:
        passed = _count_token(content, "passed")
        failed = _count_token(content, "failed")
        passed_text = "unknown" if passed is None else str(passed)
        failed_text = "unknown" if failed is None else str(failed)
        return (
            f"[{tool_name}]{suffix} "
            f"{passed_text} passed / {failed_text} failed"
        )

    if tool_name == "write_file":
        status = _write_status(content, failed)
        return f"[write_file]{suffix} {status}"

    if tool_name == "patch_file":
        status = _write_status(content, failed)
        return f"[patch_file]{suffix} {status}"

    return f"[{tool_name}]{suffix} ({len(content)} chars)"


def omit_tool_call_payloads(message: dict) -> None:
    tool_calls = message.get("tool_calls")
    if not tool_calls:
        return

    compacted = []
    for tool_call in tool_calls:
        payload = _tool_call_as_dict(tool_call)
        function = payload.get("function") or {}
        name = function.get("name") or ""
        arguments = function.get("arguments") or "{}"
        function["arguments"] = _omit_large_arguments(name, arguments)
        payload["function"] = function
        compacted.append(payload)

    message["tool_calls"] = compacted


def _has_tool_calls(message: dict) -> bool:
    return (
        message.get("role") == "assistant"
        and bool(message.get("tool_calls"))
    )


def _tool_call_index(messages: list) -> dict:
    mapping = {}

    for message in messages:
        for tool_call in message.get("tool_calls") or []:
            payload = _tool_call_as_dict(tool_call)
            function = payload.get("function") or {}
            call_id = payload.get("id")
            if not call_id:
                continue
            mapping[call_id] = (
                function.get("name") or "tool",
                function.get("arguments") or "{}",
            )

    return mapping


def _tool_call_as_dict(tool_call) -> dict:
    if isinstance(tool_call, dict):
        payload = dict(tool_call)
        function = payload.get("function")
        if isinstance(function, dict):
            payload["function"] = dict(function)
        return payload

    function = getattr(tool_call, "function", None)
    return {
        "id": getattr(tool_call, "id", ""),
        "type": getattr(tool_call, "type", "function"),
        "function": {
            "name": getattr(function, "name", ""),
            "arguments": getattr(function, "arguments", "{}"),
        },
    }


def _parse_arguments(arguments) -> dict:
    if isinstance(arguments, dict):
        return arguments

    if not isinstance(arguments, str) or not arguments.strip():
        return {}

    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _omit_large_arguments(tool_name: str, arguments: str) -> str:
    args = _parse_arguments(arguments)

    if not args:
        if len(arguments) > DEFAULT_MAX_TOOL_CHARS:
            return json.dumps(
                {"_omitted": f"{len(arguments)} chars"},
                ensure_ascii=False,
            )
        return arguments

    if tool_name == "write_file" and "content" in args:
        size = len(str(args["content"]))
        args["content"] = f"[omitted, {size} chars]"

    if tool_name == "patch_file" and "new_text" in args:
        size = len(str(args["new_text"]))
        if size > DEFAULT_MAX_TOOL_CHARS:
            args["new_text"] = f"[omitted, {size} chars]"

    return json.dumps(args, ensure_ascii=False)


def _count_token(content: str, token: str) -> int | None:
    matches = list(
        re.finditer(
            rf"(\d+)\s+{token}",
            content,
            re.IGNORECASE,
        )
    )
    if matches:
        return int(matches[-1].group(1))
    return None


def _tool_result_failed(content: str) -> bool:
    lowered = content.lower()
    return (
        "tool execution failed:" in lowered
        or "tool argument parsing failed:" in lowered
        or "access outside the workspace" in lowered
    )


def _write_status(content: str, failed: bool) -> str:
    if failed:
        return "FAILED"
    if "successfully" in content.lower():
        return "OK"
    return "UNKNOWN"
