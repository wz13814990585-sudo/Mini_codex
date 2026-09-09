"""Compatibility exports for structured tracing."""

from .observability.trace import TraceEvent, TraceEventType, TraceRecorder, TraceSummary

__all__ = ["TraceEvent", "TraceEventType", "TraceRecorder", "TraceSummary"]
