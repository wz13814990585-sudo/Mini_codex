"""Runtime execution and cancellation mechanics."""

__all__ = [
    "AsyncAgentRunner",
    "AsyncAgentTask",
    "AsyncStreamEvent",
    "AsyncTaskResult",
    "AsyncTaskStatus",
    "CancellationSnapshot",
    "CancellationToken",
    "CancellableLLMClient",
    "CancellableToolExecutor",
    "ExecutionCancelled",
    "PreparedToolCall",
    "ToolExecution",
    "ToolExecutor",
]


def __getattr__(name):
    if name in {"CancellationSnapshot", "CancellationToken", "ExecutionCancelled"}:
        from .execution_control import CancellationSnapshot, CancellationToken, ExecutionCancelled

        return {
            "CancellationSnapshot": CancellationSnapshot,
            "CancellationToken": CancellationToken,
            "ExecutionCancelled": ExecutionCancelled,
        }[name]
    if name in {"PreparedToolCall", "ToolExecution", "ToolExecutor"}:
        from .tool_executor import PreparedToolCall, ToolExecution, ToolExecutor

        return {
            "PreparedToolCall": PreparedToolCall,
            "ToolExecution": ToolExecution,
            "ToolExecutor": ToolExecutor,
        }[name]
    if name in {
        "AsyncAgentRunner",
        "AsyncAgentTask",
        "AsyncStreamEvent",
        "AsyncTaskResult",
        "AsyncTaskStatus",
        "CancellableLLMClient",
        "CancellableToolExecutor",
    }:
        from .async_runtime import (
            AsyncAgentRunner,
            AsyncAgentTask,
            AsyncStreamEvent,
            AsyncTaskResult,
            AsyncTaskStatus,
            CancellableLLMClient,
            CancellableToolExecutor,
        )

        return locals()[name]
    raise AttributeError(name)
