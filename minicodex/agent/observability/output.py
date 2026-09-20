"""User-selectable CLI output detail."""

from __future__ import annotations

from enum import Enum


class OutputLevel(str, Enum):
    NORMAL = "normal"
    VERBOSE = "verbose"
    DEBUG = "debug"

    @classmethod
    def parse(cls, value) -> "OutputLevel":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value or cls.NORMAL.value).strip().lower())
        except ValueError as exc:
            raise ValueError("output_level 必须为 normal、verbose 或 debug") from exc
