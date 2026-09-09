"""Editing reliability and rollback coordination."""

__all__ = [
    "CHECKPOINTED_EDIT_TOOLS",
    "EDIT_TOOLS",
    "Checkpoint",
    "CheckpointManager",
    "CheckpointingToolExecutor",
    "EditFailureType",
    "EditRetryPolicy",
    "EditStrategy",
    "EditStrategyHint",
    "FileSnapshot",
    "PendingEditRetry",
    "RollbackCoordinator",
    "RollbackEngine",
    "classify_edit_exception",
    "reason_for_edit_failure",
]


def __getattr__(name):
    if name in {"EditStrategy", "EditStrategyHint"}:
        from .edit_strategy import EditStrategy, EditStrategyHint

        return {"EditStrategy": EditStrategy, "EditStrategyHint": EditStrategyHint}[name]
    if name in {"EditFailureType", "classify_edit_exception", "reason_for_edit_failure"}:
        from .edit_failure import EditFailureType, classify_edit_exception, reason_for_edit_failure

        return {
            "EditFailureType": EditFailureType,
            "classify_edit_exception": classify_edit_exception,
            "reason_for_edit_failure": reason_for_edit_failure,
        }[name]
    if name in {"EDIT_TOOLS", "EditRetryPolicy", "PendingEditRetry"}:
        from .edit_retry import EDIT_TOOLS, EditRetryPolicy, PendingEditRetry

        return {
            "EDIT_TOOLS": EDIT_TOOLS,
            "EditRetryPolicy": EditRetryPolicy,
            "PendingEditRetry": PendingEditRetry,
        }[name]
    if name in {"Checkpoint", "CheckpointManager", "FileSnapshot"}:
        from .checkpoint import Checkpoint, CheckpointManager, FileSnapshot

        return {
            "Checkpoint": Checkpoint,
            "CheckpointManager": CheckpointManager,
            "FileSnapshot": FileSnapshot,
        }[name]
    if name in {"CHECKPOINTED_EDIT_TOOLS", "CheckpointingToolExecutor"}:
        from .checkpoint_executor import CHECKPOINTED_EDIT_TOOLS, CheckpointingToolExecutor

        return {
            "CHECKPOINTED_EDIT_TOOLS": CHECKPOINTED_EDIT_TOOLS,
            "CheckpointingToolExecutor": CheckpointingToolExecutor,
        }[name]
    if name == "RollbackEngine":
        from .rollback import RollbackEngine

        return RollbackEngine
    if name == "RollbackCoordinator":
        from .rollback_coordinator import RollbackCoordinator

        return RollbackCoordinator
    raise AttributeError(name)
