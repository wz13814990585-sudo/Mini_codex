"""Evaluation infrastructure for MiniCodex."""

from .checks import (
    EvaluationCheckRunner,
)
from .harness import (
    EvaluationHarness,
    compare_summaries,
)
from .models import (
    CheckResult,
    EvaluationCase,
    EvaluationCheck,
    EvaluationComparison,
    EvaluationResult,
    EvaluationSummary,
    FAILURE_CATEGORIES,
)
from .benchmark_v1 import BENCHMARK_VERSION, BenchmarkFixture, fixtures, smoke_fixtures
from .profiles import EvaluationProfile
from .preflight import BenchmarkPreflightResult, PreflightCheck, benchmark_preflight
from .reporting import compare_profiles, failure_clusters


__all__ = [
    "CheckResult",
    "EvaluationCase",
    "EvaluationCheck",
    "EvaluationCheckRunner",
    "EvaluationComparison",
    "EvaluationHarness",
    "EvaluationResult",
    "EvaluationSummary",
    "compare_summaries",
    "BENCHMARK_VERSION",
    "BenchmarkFixture",
    "EvaluationProfile",
    "fixtures",
    "smoke_fixtures",
    "compare_profiles",
    "failure_clusters",
    "FAILURE_CATEGORIES",
    "BenchmarkPreflightResult",
    "PreflightCheck",
    "benchmark_preflight",
]
