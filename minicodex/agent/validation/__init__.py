"""Validation evidence, targeting, and policy domain."""

from .evidence import (
    FailureComparison,
    FailureDelta,
    ValidationEvidence,
    ValidationNextAction,
    ValidationOutcome,
    ValidationPurpose,
    ValidationScope,
)
from .pipeline import ValidationPipeline
from .ledger import ValidationLedger
from .validator_resolver import ValidatorResolution, ValidatorResolver
from .verification_spec import (BrowserVerificationSpec, CommandVerificationSpec, FileVerificationSpec,
                                HttpVerificationSpec, SemanticVerificationSpec, TestVerificationSpec)
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
    "ValidationLedger",
    "ValidatorResolution",
    "ValidatorResolver",
    "BrowserVerificationSpec",
    "CommandVerificationSpec",
    "FileVerificationSpec",
    "HttpVerificationSpec",
    "SemanticVerificationSpec",
    "TestVerificationSpec",
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
