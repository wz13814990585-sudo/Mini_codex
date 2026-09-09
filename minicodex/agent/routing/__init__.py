"""Deterministic task intent and complexity routing."""

from .intent import IntentClassifier, TaskIntent
from .complexity import ComplexityRoute, ComplexityRouter
from .execution_mode import ExecutionMode
from .task_router import RoutingRule, TaskRoute, TaskRouter


def __getattr__(name):
    """Load policy exports lazily to keep routing/validation acyclic."""

    if name in {"ExecutionPolicy", "FAST_TOOL_NAMES", "policy_for"}:
        from .execution_policy import ExecutionPolicy, FAST_TOOL_NAMES, policy_for

        return {
            "ExecutionPolicy": ExecutionPolicy,
            "FAST_TOOL_NAMES": FAST_TOOL_NAMES,
            "policy_for": policy_for,
        }[name]
    raise AttributeError(name)

__all__ = [
    "ComplexityRoute",
    "ComplexityRouter",
    "IntentClassifier",
    "ExecutionMode",
    "ExecutionPolicy",
    "FAST_TOOL_NAMES",
    "policy_for",
    "RoutingRule",
    "TaskIntent",
    "TaskRoute",
    "TaskRouter",
]
