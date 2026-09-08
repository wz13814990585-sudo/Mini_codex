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
            raise ValueError("output_level must be normal, verbose, or debug") from exc
