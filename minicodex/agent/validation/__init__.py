"""Validation evidence, targeting, and policy domain."""

from .pipeline import (
    ValidationEvidence,
    ValidationNextAction,
    ValidationOutcome,
    ValidationPipeline,
    ValidationPurpose,
    ValidationScope,
    ValidationState,
)
from .selector import ValidationSelection, ValidationSelector
from .test_index import IndexedTest, TestIndex
from .test_target_resolver import TestTargetResolution, TestTargetResolver
from .regression_policy import RegressionPolicy, RegressionRequirement
from .completion import CompletionDecision, CompletionGate, CompletionStatus, TaskOutcome
from .relevant_paths import RelevantPathResolver, RelevantPathSet


def __getattr__(name):
    """Load the Agent-state completion policy without creating init cycles."""

    if name == "TaskCompletionPolicy":
        from .completion_policy import TaskCompletionPolicy

        return TaskCompletionPolicy
    raise AttributeError(name)

__all__ = [
    "ValidationEvidence",
    "ValidationNextAction",
    "ValidationOutcome",
    "ValidationPipeline",
    "ValidationPurpose",
    "ValidationScope",
    "ValidationState",
    "ValidationSelection",
    "ValidationSelector",
    "IndexedTest",
    "TestIndex",
    "TestTargetResolution",
    "TestTargetResolver",
    "RegressionPolicy",
    "RegressionRequirement",
    "CompletionDecision",
    "CompletionGate",
    "CompletionStatus",
    "TaskCompletionPolicy",
    "TaskOutcome",
    "RelevantPathResolver",
    "RelevantPathSet",
]
