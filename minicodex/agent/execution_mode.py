"""Execution modes selected before a MiniCodex task starts."""

from enum import Enum


class ExecutionMode(str, Enum):
    FAST = "fast"
    STANDARD = "standard"
    COMPLEX = "complex"

