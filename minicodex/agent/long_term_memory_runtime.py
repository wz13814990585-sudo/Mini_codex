"""Compatibility exports for persistent-memory runtime integration."""

from .memory.long_term_memory_runtime import attach_long_term_memory, build_task_memory_record

__all__ = ["attach_long_term_memory", "build_task_memory_record"]
