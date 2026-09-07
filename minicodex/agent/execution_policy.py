"""Centralized policy differences for the shared Agent Harness."""

from dataclasses import dataclass

from .execution_mode import ExecutionMode
from .regression_policy import RegressionRequirement


@dataclass(frozen=True)
class ExecutionPolicy:
    mode: ExecutionMode
    use_plan: bool
    max_steps: int
    max_plan_steps: int
    max_inspection_calls: int | None
    max_no_progress_steps: int
    require_acceptance: bool
    regression_requirement: RegressionRequirement
    enable_long_term_memory: bool
    enable_heavy_recovery: bool
    enable_replan: bool
    repo_map_refresh_policy: str
    finalization_threshold: int
    compact_context: bool


def policy_for(mode: ExecutionMode) -> ExecutionPolicy:
    if mode == ExecutionMode.FAST:
        return ExecutionPolicy(
            mode=mode,
            use_plan=False,
            max_steps=6,
            max_plan_steps=0,
            max_inspection_calls=3,
            max_no_progress_steps=3,
            require_acceptance=True,
            regression_requirement=RegressionRequirement.NOT_APPLICABLE,
            enable_long_term_memory=False,
            enable_heavy_recovery=False,
            enable_replan=False,
            repo_map_refresh_policy="task_start_and_after_edit",
            finalization_threshold=2,
            compact_context=True,
        )

    if mode == ExecutionMode.STANDARD:
        return ExecutionPolicy(
            mode=mode,
            use_plan=True,
            max_steps=12,
            max_plan_steps=4,
            max_inspection_calls=6,
            max_no_progress_steps=4,
            require_acceptance=True,
            regression_requirement=RegressionRequirement.RELEVANT_ONLY,
            enable_long_term_memory=False,
            enable_heavy_recovery=True,
            enable_replan=True,
            repo_map_refresh_policy="revision_cached",
            finalization_threshold=3,
            compact_context=False,
        )

    return ExecutionPolicy(
        mode=ExecutionMode.COMPLEX,
        use_plan=True,
        max_steps=24,
        max_plan_steps=6,
        max_inspection_calls=None,
        max_no_progress_steps=5,
        require_acceptance=True,
        regression_requirement=RegressionRequirement.REQUIRED,
        enable_long_term_memory=True,
        enable_heavy_recovery=True,
        enable_replan=True,
        repo_map_refresh_policy="every_turn",
        finalization_threshold=3,
        compact_context=False,
    )

