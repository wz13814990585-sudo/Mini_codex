"""Coordinate validation-regression rollback without owning validation policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..progress import ProgressKind, ProgressSignal
from ..reason_codes import ReasonCode

if TYPE_CHECKING:
    from ..orchestration.control_decision import ControlDecision


class RollbackCoordinator:
    def coordinate(self, agent, evidence, validation_progress) -> ControlDecision | None:
        from ..orchestration.control_decision import ControlDecision

        pipeline = getattr(agent, "validation_pipeline", None)
        manager = getattr(agent, "checkpoint_manager", None)
        engine = getattr(agent, "rollback_engine", None)
        if pipeline is None or manager is None or engine is None:
            return None
        if not validation_progress.crossed_revision:
            return None
        current_revision = pipeline.state.edit_revision
        if evidence.edit_revision != current_revision:
            return None
        if validation_progress.current_revision != current_revision:
            return None
        checkpoint = manager.latest_for_revision(evidence.edit_revision)
        if checkpoint is None or not checkpoint.sealed or checkpoint.rolled_back:
            return None

        print("\n[Automatic Rollback]")
        print(
            f"Validation regression detected: {validation_progress.previous_failed} "
            f"failed -> {validation_progress.current_failed} failed."
        )
        result = engine.rollback(checkpoint.checkpoint_id)
        summary = getattr(agent, "working_summary", None)
        if summary is not None:
            summary.record_tool_result(
                tool_name="automatic_rollback",
                arguments={
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "edit_revision": evidence.edit_revision,
                    "validation_key": validation_progress.validation_key,
                    "failed_before": validation_progress.previous_failed,
                    "failed_after": validation_progress.current_failed,
                },
                result=result,
            )
        if not result.success:
            return ControlDecision(
                restart=True,
                followup_message=(
                    "Validation regressed and automatic rollback failed. "
                    f"{result.to_llm_text()} Inspect the physical workspace before editing."
                ),
                skipped_reason="automatic rollback failed",
                reason_code=ReasonCode.BLOCKED,
            )

        rollback_revision = pipeline.record_edit()
        requirements = getattr(agent, "task_requirements", None)
        if requirements is not None:
            requirements.invalidate_revision(rollback_revision)
        if hasattr(agent, "_repo_map_initialized"):
            agent._repo_map_initialized = False
            agent._repo_map_revision = None
        summary_memory = getattr(getattr(agent, "working_summary", None), "memory", None)
        if summary_memory is not None:
            # Rollback may invalidate several post-edit repository facts.
            summary_memory.reset()
        step_evidence = getattr(agent, "step_evidence", None)
        if step_evidence is not None:
            step_evidence.reset()
        edit_retry = getattr(agent, "edit_retry", None)
        if edit_retry is not None:
            edit_retry.reset()
        metrics = getattr(agent, "execution_metrics", None)
        if metrics is not None:
            metrics.record_rollback()
        if hasattr(agent, "rollback_revision"):
            agent.rollback_revision += 1
        agent.progress.reset()
        agent.recovery.mark_progress()
        controller = getattr(agent, "action_controller", None)
        if controller is not None:
            controller.observe_action(
                "automatic_rollback",
                agent.task_progress_state(),
                ProgressSignal(ProgressKind.OBSERVATION, "Rollback is not positive advancement."),
            )
        print("\n[Rollback Successful]")
        print(f"Restored checkpoint: {checkpoint.checkpoint_id}")
        return ControlDecision(
            restart=True,
            followup_message=(
                "The Harness automatically rolled back the regressed edit. "
                f"Checkpoint {checkpoint.checkpoint_id} was restored at revision "
                f"{rollback_revision}. Previous validation is stale; choose a materially "
                "different repair."
            ),
            skipped_reason="automatic rollback changed the workspace revision",
        )
