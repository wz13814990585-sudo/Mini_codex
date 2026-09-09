"""Import contracts for the domain package migration."""


def test_major_domain_apis_import_without_cycles():
    from ..agent.agent import MiniCodexAgent
    from ..agent.editing import RollbackCoordinator
    from ..agent.progress import ProgressSignal
    from ..agent.routing import TaskIntent, TaskRouter
    from ..agent.runtime import ToolExecutor
    from ..agent.validation import ValidationPipeline
    from ..tools.registry import ToolRegistry

    assert all(
        value is not None
        for value in (
            MiniCodexAgent,
            RollbackCoordinator,
            ProgressSignal,
            TaskIntent,
            TaskRouter,
            ToolExecutor,
            ValidationPipeline,
            ToolRegistry,
        )
    )


def test_agent_compatibility_modules_reexport_canonical_objects():
    from ..agent.action_controller import ActionController as LegacyActionController
    from ..agent.completion import CompletionStatus as LegacyCompletionStatus
    from ..agent.dependency_resolver import DependencyResolver as LegacyDependencyResolver
    from ..agent.execution_mode import ExecutionMode as LegacyExecutionMode
    from ..agent.tool_executor import ToolExecutor as LegacyToolExecutor
    from ..agent.trace import TraceRecorder as LegacyTraceRecorder
    from ..agent.working_memory import WorkingMemory as LegacyWorkingMemory
    from ..agent.dependency import DependencyResolver
    from ..agent.observability import TraceRecorder
    from ..agent.progress import ActionController
    from ..agent.routing import ExecutionMode
    from ..agent.runtime import ToolExecutor
    from ..agent.validation import CompletionStatus
    from ..agent.memory import WorkingMemory

    assert LegacyActionController is ActionController
    assert LegacyCompletionStatus is CompletionStatus
    assert LegacyDependencyResolver is DependencyResolver
    assert LegacyExecutionMode is ExecutionMode
    assert LegacyToolExecutor is ToolExecutor
    assert LegacyTraceRecorder is TraceRecorder
    assert LegacyWorkingMemory is WorkingMemory


def test_tool_compatibility_modules_reexport_canonical_objects():
    from ..tools.patch_file import PatchFileTool as LegacyPatchFileTool
    from ..tools.read_file import ReadFileTool as LegacyReadFileTool
    from ..tools.run_tests import RunTestsTool as LegacyRunTestsTool
    from ..tools.validate_static_web import ValidateStaticWebTool as LegacyStaticWebTool
    from ..tools.editing import PatchFileTool
    from ..tools.execution import RunTestsTool
    from ..tools.filesystem import ReadFileTool
    from ..tools.validation import ValidateStaticWebTool

    assert LegacyPatchFileTool is PatchFileTool
    assert LegacyReadFileTool is ReadFileTool
    assert LegacyRunTestsTool is RunTestsTool
    assert LegacyStaticWebTool is ValidateStaticWebTool
