"""Fair, explicit feature profiles for benchmark comparisons."""

from __future__ import annotations

from dataclasses import replace
from enum import Enum

from ..agent.routing import ExecutionMode, ExecutionPolicy, policy_for


class EvaluationProfile(str, Enum):
    BASELINE = "baseline"
    MINICODEX = "minicodex"


def benchmark_policy(
    profile: EvaluationProfile | str,
    *,
    mode: ExecutionMode,
    max_steps: int,
    needs_plan: bool | None = None,
) -> ExecutionPolicy:
    """Return one shared-loop policy with an equal main-step budget.

    The baseline remains a capable read/edit/test agent.  It removes planning,
    replanning, long-term memory and heavy recovery, while retaining the same
    tools, model, deterministic completion gate and oracle as MiniCodex.
    """

    selected = EvaluationProfile(profile)
    current = replace(policy_for(mode, needs_plan=needs_plan), max_steps=max_steps)
    if selected is EvaluationProfile.MINICODEX:
        return current
    return replace(
        current,
        use_plan=False,
        max_plan_steps=0,
        enable_long_term_memory=False,
        enable_heavy_recovery=False,
        enable_replan=False,
        max_replans=0,
        repo_map_refresh_policy="task_start_and_after_edit",
    )
