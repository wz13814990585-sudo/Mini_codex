"""Validation evidence, targeting, and policy domain."""

from .pipeline import (
    FailureComparison,
    FailureDelta,
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
from .completion_policy import TaskCompletionPolicy
from .relevant_paths import RelevantPathResolver, RelevantPathSet
from .semantic_judge import (
    JudgeContextBuilder, JudgeTelemetry, RegressionAssessment,
    RegressionClassification, RegressionRecommendation,
    RegressionRecoveryPolicy, SemanticRegressionJudge,
)

__all__ = [
    "FailureDelta",
    "FailureComparison",
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
    "JudgeContextBuilder",
    "JudgeTelemetry",
    "RegressionAssessment",
    "RegressionClassification",
    "RegressionRecommendation",
    "RegressionRecoveryPolicy",
    "SemanticRegressionJudge",
]
