"""Coordinate validation-regression rollback without owning validation policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..progress import ProgressKind, ProgressSignal
from ..reason_codes import ReasonCode
from ..task_state import RuntimeEventType

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

        print("\n[自动回滚]")
        print(
            f"检测到验证回归：失败数从 {validation_progress.previous_failed} "
            f"变为 {validation_progress.current_failed}。"
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
                    "验证发生回归且自动回滚失败。"
                    f"{result.to_llm_text()} 请在编辑前先检查物理工作区。"
                ),
                skipped_reason="自动回滚失败",
                reason_code=ReasonCode.BLOCKED,
            )

        rollback_revision = pipeline.record_edit()
        session = getattr(agent, "workspace_session", None)
        if session is not None:
            session.invalidate(checkpoint.snapshot.path)
        requirements = getattr(agent, "task_requirements", None)
        if requirements is not None:
            requirements.invalidate_revision(rollback_revision)
            sync_requirements = getattr(agent, "sync_requirements_state", None)
            if callable(sync_requirements):
                sync_requirements()
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
        apply_event = getattr(agent, "apply_runtime_event", None)
        if callable(apply_event):
            apply_event(
                RuntimeEventType.ROLLBACK_APPLIED,
                edit_revision=rollback_revision,
                rollback_revision=getattr(agent, "rollback_revision", 1),
                checkpoint_id=checkpoint.checkpoint_id,
                restored_paths=(checkpoint.snapshot.path,),
            )
        agent.progress.reset()
        agent.recovery.mark_progress()
        controller = getattr(agent, "action_controller", None)
        if controller is not None:
            controller.observe_action(
                "automatic_rollback",
                agent.task_progress_state(),
                ProgressSignal(ProgressKind.OBSERVATION, "回滚不算正向进展。"),
            )
        print("\n[回滚成功]")
        print(f"已恢复检查点：{checkpoint.checkpoint_id}")
        return ControlDecision(
            restart=True,
            followup_message=(
                "Harness 已自动回滚发生回归的编辑。"
                f"检查点 {checkpoint.checkpoint_id} 已恢复到版本 "
                f"{rollback_revision}。此前验证已过期；请选择实质不同的修复方案。"
            ),
            skipped_reason="自动回滚已改变工作区版本",
        )
