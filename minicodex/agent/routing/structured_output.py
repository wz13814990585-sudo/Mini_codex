"""Strict, bounded JSON normalization for control-model responses."""

import json


class StructuredOutputError(ValueError):
    pass


def parse_bounded_json_object(raw: str, *, max_chars: int = 8_000) -> dict:
    text = str(raw or "").strip()
    if not text or len(text) > max_chars:
        raise StructuredOutputError("empty or oversized structured response")
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise StructuredOutputError("invalid markdown fence")
        if lines[0].strip().casefold() not in {"```", "```json"}:
            raise StructuredOutputError("unsupported markdown fence")
        text = "\n".join(lines[1:-1]).strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise StructuredOutputError("response must contain only one JSON object")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError("malformed JSON") from exc
    if not isinstance(value, dict):
        raise StructuredOutputError("structured response must be an object")
    return value
