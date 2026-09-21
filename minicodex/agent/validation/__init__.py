"""Validation evidence, targeting, and policy domain."""

from .evidence import (
    ExecutionStatus,
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
from .executor import (
    ValidationExecutionResult,
    ValidationExecutionState,
    ValidationExecutor,
)
from .validator_resolver import ValidatorResolution, ValidatorResolver
from .contracts import (
    BrowserAction,
    BrowserAssertion,
    BrowserInteractionContract,
    BrowserNoOpBehavior,
    CommandContract,
    FileContainsContract,
    FileExistsContract,
    HttpContract,
    NodeBehaviorContract,
    PythonBehaviorContract,
    SemanticContract,
    TestTargetContract,
    VerificationContract,
    parse_contract,
)
from .test_index import IndexedTest, TestIndex
from .test_target_resolver import TestTargetResolution, TestTargetResolver
from .regression_policy import RegressionPolicy, RegressionRequirement
from .completion import CompletionDecision, CompletionStatus, TaskOutcome
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
    "ExecutionStatus",
    "ValidationEvidence",
    "ValidationNextAction",
    "ValidationOutcome",
    "ValidationPipeline",
    "ValidationPurpose",
    "ValidationScope",
    "ValidationLedger",
    "ValidationExecutionResult",
    "ValidationExecutionState",
    "ValidationExecutor",
    "ValidatorResolution",
    "ValidatorResolver",
    "BrowserAction",
    "BrowserAssertion",
    "BrowserInteractionContract",
    "BrowserNoOpBehavior",
    "CommandContract",
    "FileContainsContract",
    "FileExistsContract",
    "HttpContract",
    "NodeBehaviorContract",
    "PythonBehaviorContract",
    "SemanticContract",
    "TestTargetContract",
    "VerificationContract",
    "parse_contract",
    "IndexedTest",
    "TestIndex",
    "TestTargetResolution",
    "TestTargetResolver",
    "RegressionPolicy",
    "RegressionRequirement",
    "CompletionDecision",
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
