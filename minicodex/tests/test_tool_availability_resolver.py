"""P0: ToolAvailabilityResolver, shared policy consistency, and ghost metrics."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from minicodex.agent.observability.metrics import ExecutionMetrics
from minicodex.agent.orchestration.tool_availability import ToolAvailabilityResolver
from minicodex.agent.progress.action_controller import ActionController
from minicodex.agent.progress.executable_tool_policy import ExecutableToolPolicy
from minicodex.agent.progress.finalization import FinalizationController
from minicodex.agent.routing import ExecutionMode, policy_for
from minicodex.agent.task_state import AgentPhase
from minicodex.tools.registry import ToolRegistry


class _StubTool:
    def __init__(self, name: str, capabilities: frozenset[str]):
        self.name = name
        self.capabilities = capabilities

    def to_schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.name,
                "parameters": {"type": "object", "properties": {}},
            },
        }


def _registry_with_core_tools() -> ToolRegistry:
    registry = ToolRegistry()
    specs = {
        "read_file": frozenset({"filesystem.read", "file.read"}),
        "list_files": frozenset({"filesystem.read"}),
        "search_code": frozenset({"code.search"}),
        "search_symbol": frozenset({"code.search", "code.symbol"}),
        "write_file": frozenset({"code.edit", "filesystem.write"}),
        "patch_file": frozenset({"code.edit", "filesystem.write"}),
        "run_command": frozenset({"process.run"}),
        "run_tests": frozenset({"test.run"}),
        "validate_static_web": frozenset({"validation.static_web"}),
        "validate_browser_app": frozenset({"validation.browser"}),
        "validate_service": frozenset({"service.validate"}),
        "git_status": frozenset({"git.inspect"}),
        "replan": frozenset({"plan.control"}),
    }
    for name, caps in specs.items():
        registry.register(_StubTool(name, caps))
    return registry


def _agent(
    *,
    phase: AgentPhase,
    registry: ToolRegistry | None = None,
    action_required: bool = False,
    consecutive_inspections: int = 0,
    validation_inspections: int = 0,
    contract: str = "",
    validator_status: str = "",
    validation_paths: tuple[str, ...] = (),
    finalization_active: bool = False,
    allow_proof_inspection: bool = False,
    mode: ExecutionMode = ExecutionMode.STANDARD,
    milestone_due: bool = False,
    edit_retry_path: str | None = None,
):
    registry = registry or _registry_with_core_tools()
    action = ActionController(registry)
    action.phase = phase
    action.action_required = action_required
    action.consecutive_inspections = consecutive_inspections
    action.validation_inspections = validation_inspections
    action.next_contract_type = contract
    action.next_required_check_id = "check-1" if contract else ""
    action.validator_resolution_status = validator_status
    action.validation_paths = validation_paths
    action.has_edit = phase in {
        AgentPhase.VALIDATING,
        AgentPhase.FIXING,
        AgentPhase.FINALIZING,
    }
    work_unit = None
    if milestone_due:
        work_unit = SimpleNamespace(
            closed=False,
            milestone_due=True,
            status="ready_for_validation",
        )
    edit_retry = None
    if edit_retry_path is not None:
        from minicodex.agent.editing.edit_failure import EditFailureType
        from minicodex.agent.editing.edit_retry import EditRetryPolicy, PendingEditRetry

        edit_retry = EditRetryPolicy()
        edit_retry.pending = PendingEditRetry(
            path=edit_retry_path,
            edit_tool="write_file",
            read_completed=False,
            failure_type=EditFailureType.STALE_CONTEXT,
        )
    return SimpleNamespace(
        registry=registry,
        action_controller=action,
        execution_policy=policy_for(mode),
        finalization=SimpleNamespace(
            active=finalization_active,
            allow_proof_inspection=allow_proof_inspection,
            restriction_reason=lambda tool_name: None,
        ),
        task_state=SimpleNamespace(phase=phase, work_unit=work_unit),
        edit_retry=edit_retry,
        dependency_resolver=None,
        execution_route=None,
    )


def _schema_names(agent) -> set[str]:
    schemas = agent.registry.get_schemas()
    return {
        s["function"]["name"]
        for s in ToolAvailabilityResolver().filter_schemas(agent, schemas)
    }


def test_validating_resolved_hides_inspection_keeps_edit_and_contract_validator():
    agent = _agent(
        phase=AgentPhase.VALIDATING,
        contract="browser_interaction",
        validator_status="resolved",
    )
    names = _schema_names(agent)
    assert "read_file" not in names
    assert "search_code" not in names
    assert "git_status" not in names
    assert "validate_browser_app" in names
    assert "validate_static_web" not in names
    assert "write_file" in names
    assert "patch_file" in names


def test_validating_target_unresolved_allows_one_inspection_then_drops():
    agent = _agent(
        phase=AgentPhase.VALIDATING,
        contract="python_behavior",
        validator_status="target_unresolved",
        validation_paths=("demo.py",),
        validation_inspections=0,
    )
    names = _schema_names(agent)
    assert "read_file" in names
    assert "search_code" in names

    agent.action_controller.validation_inspections = 1
    names_after = _schema_names(agent)
    assert "read_file" not in names_after
    assert "search_code" not in names_after
    assert "run_command" in names_after
    assert "write_file" in names_after


def test_fixing_without_targeted_read_allows_one_read():
    agent = _agent(
        phase=AgentPhase.FIXING,
        contract="python_behavior",
        consecutive_inspections=0,
    )
    names = _schema_names(agent)
    assert "read_file" in names
    assert "list_files" not in names
    assert "search_code" not in names
    assert "write_file" in names


def test_fixing_after_targeted_read_hides_inspection():
    agent = _agent(
        phase=AgentPhase.FIXING,
        contract="python_behavior",
        consecutive_inspections=1,
    )
    names = _schema_names(agent)
    assert "read_file" not in names
    assert "list_files" not in names
    assert "search_code" not in names
    assert "write_file" in names
    assert "run_command" in names


def test_fixing_list_files_bypass_still_rejected_by_action_controller():
    agent = _agent(
        phase=AgentPhase.FIXING,
        contract="python_behavior",
        consecutive_inspections=0,
    )
    assert "list_files" not in _schema_names(agent)
    reason = agent.action_controller.restriction_reason(
        "list_files", {"path": "."}, agent.execution_policy
    )
    assert reason is not None
    assert "侦察" in reason or "探查" in reason


def test_action_required_hides_pure_inspection():
    agent = _agent(
        phase=AgentPhase.INSPECTING,
        action_required=True,
        consecutive_inspections=3,
        contract="python_behavior",
    )
    names = _schema_names(agent)
    assert "read_file" not in names
    assert "search_code" not in names
    assert "list_files" not in names
    assert "write_file" in names
    assert "run_command" in names


def test_browser_interaction_exposes_browser_not_static_web():
    agent = _agent(
        phase=AgentPhase.VALIDATING,
        contract="browser_interaction",
        validator_status="resolved",
    )
    names = _schema_names(agent)
    assert "validate_browser_app" in names
    assert "validate_static_web" not in names


def test_python_behavior_exposes_process_run_not_service_validate():
    agent = _agent(
        phase=AgentPhase.VALIDATING,
        contract="python_behavior",
        validator_status="resolved",
    )
    names = _schema_names(agent)
    assert "run_command" in names
    assert "validate_service" not in names


def test_action_controller_still_blocks_bypassed_schema_calls():
    agent = _agent(
        phase=AgentPhase.VALIDATING,
        contract="browser_interaction",
        validator_status="resolved",
    )
    reason = agent.action_controller.restriction_reason(
        "validate_static_web",
        {"path": "index.html"},
        agent.execution_policy,
    )
    assert reason is not None
    search_reason = agent.action_controller.restriction_reason(
        "search_code",
        {"query": "x"},
        agent.execution_policy,
    )
    assert search_reason is not None


def test_milestone_due_hides_edit_keeps_validator():
    agent = _agent(
        phase=AgentPhase.VALIDATING,
        contract="python_behavior",
        validator_status="resolved",
        milestone_due=True,
    )
    names = _schema_names(agent)
    assert "write_file" not in names
    assert "patch_file" not in names
    assert "run_command" in names
    from minicodex.agent.orchestration.tool_batch import resolve_tool_restriction

    blocked = resolve_tool_restriction(agent, "write_file", {"path": "a.py", "content": "x"})
    assert blocked is not None
    assert blocked.failure_type == "validation_milestone"


def test_edit_retry_pending_allows_read_under_action_required():
    agent = _agent(
        phase=AgentPhase.ACTING,
        action_required=True,
        consecutive_inspections=3,
        contract="python_behavior",
        edit_retry_path="src/routes/square.js",
    )
    names = _schema_names(agent)
    assert "read_file" in names
    assert "write_file" not in names
    assert "list_files" not in names
    assert "search_code" not in names

    from minicodex.agent.orchestration.tool_batch import resolve_tool_restriction

    ok = resolve_tool_restriction(
        agent, "read_file", {"path": "src/routes/square.js"}
    )
    assert ok is None
    still_blocked = resolve_tool_restriction(
        agent, "write_file", {"path": "src/routes/square.js", "content": "x"}
    )
    assert still_blocked is not None


def test_advertised_subseteq_executable_consistency():
    cases = [
        _agent(phase=AgentPhase.INSPECTING, contract="python_behavior"),
        _agent(
            phase=AgentPhase.VALIDATING,
            contract="browser_interaction",
            validator_status="resolved",
        ),
        _agent(
            phase=AgentPhase.VALIDATING,
            contract="python_behavior",
            validator_status="resolved",
        ),
        _agent(
            phase=AgentPhase.VALIDATING,
            contract="python_behavior",
            validator_status="resolved",
            milestone_due=True,
        ),
        _agent(phase=AgentPhase.FIXING, contract="pytest", consecutive_inspections=0),
        _agent(phase=AgentPhase.FIXING, contract="pytest", consecutive_inspections=1),
        _agent(
            phase=AgentPhase.FINALIZING,
            contract="python_behavior",
            validator_status="resolved",
            finalization_active=True,
        ),
        _agent(
            phase=AgentPhase.INSPECTING,
            action_required=True,
            consecutive_inspections=5,
            contract="python_behavior",
        ),
        _agent(
            phase=AgentPhase.ACTING,
            action_required=True,
            consecutive_inspections=2,
            contract="python_behavior",
        ),
        _agent(
            phase=AgentPhase.ACTING,
            action_required=True,
            consecutive_inspections=2,
            contract="python_behavior",
            edit_retry_path="a.py",
        ),
    ]
    resolver = ToolAvailabilityResolver()
    for agent in cases:
        snap = resolver.snapshot(agent)
        advertised = _schema_names(agent)
        assert "list_files" not in advertised or snap.state.phase not in {
            AgentPhase.FIXING,
        }
        if snap.state.milestone_due:
            assert "write_file" not in advertised
            assert "patch_file" not in advertised
        for name in advertised:
            caps = agent.registry.capabilities_for(name)
            block = ExecutableToolPolicy.capability_block_reason(
                snap.state,
                tool_name=name,
                capabilities=caps,
            )
            assert block is None, f"{name} advertised but capability-blocked: {block}"
            if agent.finalization.active and name in FinalizationController.BLOCKED_TOOLS:
                pytest.fail(f"{name} advertised under finalization but listed blocked")
            if snap.state.validator_resolution_status == "target_unresolved":
                continue
            args = {}
            caps = agent.registry.capabilities_for(name)
            if "process.run" in caps:
                args = {"purpose": "acceptance"}
            if name == "read_file" and snap.state.edit_retry_path:
                args = {"path": snap.state.edit_retry_path}
            shared = agent.action_controller.restriction_reason(
                name,
                args,
                agent.execution_policy,
                finalization_active=bool(agent.finalization.active),
                allow_proof_inspection=bool(agent.finalization.allow_proof_inspection),
                milestone_due=bool(snap.state.milestone_due),
                edit_retry_needs_read=bool(snap.state.edit_retry_needs_read),
                edit_retry_path=str(snap.state.edit_retry_path or ""),
            )
            assert shared is None, (
                f"{name} advertised but ActionController blocks under "
                f"phase={snap.state.phase} action_required={snap.state.action_required}: {shared}"
            )


def test_ghost_metric_full_partial_executed_and_text_only():
    metrics = ExecutionMetrics()

    metrics.agent_steps = 1
    metrics.begin_agent_step()
    metrics.note_step_tool_call()
    metrics.note_step_tool_blocked()
    metrics.finalize_agent_step()
    assert metrics.ghost_step_count == 1
    assert metrics.executed_tool_turn_count == 0
    assert metrics.blocked_tool_selection_count == 1
    assert metrics.text_only_step_count == 0

    metrics.agent_steps = 2
    metrics.begin_agent_step()
    metrics.note_step_tool_call()
    metrics.note_step_tool_call()
    metrics.note_step_tool_requested()
    metrics.note_step_tool_blocked()
    metrics.note_step_productive()
    metrics.finalize_agent_step()
    assert metrics.ghost_step_count == 1
    assert metrics.executed_tool_turn_count == 1
    assert metrics.blocked_tool_selection_count == 2
    assert metrics.productive_step_count == 1

    metrics.agent_steps = 3
    metrics.begin_agent_step()
    metrics.note_step_tool_call()
    metrics.note_step_tool_requested()
    metrics.finalize_agent_step()
    assert metrics.executed_tool_turn_count == 2
    assert metrics.ghost_step_count == 1

    metrics.agent_steps = 4
    metrics.begin_agent_step()
    metrics.finalize_agent_step()
    assert metrics.text_only_step_count == 1
    assert metrics.ghost_step_rate == pytest.approx(0.25)


def test_shared_policy_state_matches_resolver_and_controller():
    agent = _agent(
        phase=AgentPhase.FIXING,
        contract="python_behavior",
        consecutive_inspections=0,
        finalization_active=True,
    )
    resolver_state = ToolAvailabilityResolver().build_state(agent)
    controller_state = agent.action_controller.executable_policy_state(
        agent.execution_policy,
        finalization_active=True,
        allow_proof_inspection=False,
    )
    assert resolver_state.phase == controller_state.phase
    assert resolver_state.action_required == controller_state.action_required
    assert resolver_state.consecutive_inspections == controller_state.consecutive_inspections
    assert resolver_state.next_contract_type == controller_state.next_contract_type
    assert resolver_state.finalization_active == controller_state.finalization_active
    assert ExecutableToolPolicy.resolve(resolver_state) == ExecutableToolPolicy.resolve(
        controller_state
    )
