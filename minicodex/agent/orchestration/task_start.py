"""Start one task from a user request and fresh task-local state."""

from __future__ import annotations

from ..context.workspace_session import ChangeImpactResolver
from ..planning.requirements import TaskRequirements
from ..routing import ExecutionMode, TaskIntent
from ..task_state import RuntimeEventType, TaskRuntime
from ..validation.plan import ValidationPlanner


class TaskBootstrapper:
    """Own request routing, task reset, contracts, and initial planning.

    ``MiniCodexAgent`` remains the public facade and composition root.  This
    class owns the ordered, task-scoped transition that used to make the
    facade responsible for both dependency wiring and task orchestration.
    """

    def start(
        self,
        agent,
        user_input: str,
        *,
        use_planning: bool | None = None,
        policy=None,
    ) -> None:
        planning_enabled = self._configure_request(
            agent,
            user_input,
            use_planning=use_planning,
            policy=policy,
        )
        self._reset_task_services(agent)
        self._build_requirements_and_validation(agent, user_input)
        self._start_runtime(agent, user_input, planning_enabled)
        self._prepare_repository_context(agent)
        self._create_initial_plan(agent, user_input, planning_enabled)

        agent.runtime_control.planning_activated = agent.active_plan is not None
        agent.refresh_runtime_context()
        agent.action_controller.reset(agent.task_progress_state())

    @staticmethod
    def _configure_request(
        agent,
        user_input: str,
        *,
        use_planning: bool | None,
        policy,
    ) -> bool:
        agent.active_user_request = user_input
        agent.workspace_session.refresh(full=True)
        agent.baseline_web_framework = agent._detect_baseline_web_framework()
        if agent.validator_resolver is not None:
            agent.validator_resolver.preferred_http_framework = (
                agent.baseline_web_framework
            )

        agent.active_plan = None
        agent.execution_policy = agent.resolve_execution_policy(
            user_input,
            policy=policy,
        )
        agent.task_requires_validation = bool(
            agent.execution_route
            and agent.execution_route.intent == TaskIntent.MODIFY
        )
        agent.safety_policy.begin_task(
            user_input,
            routed_intent=getattr(agent.execution_route, "intent", None),
        )
        agent.final_response_mode = agent.completion_handler.response_mode(agent)
        planning_enabled = bool(
            agent.execution_policy.use_plan
            and use_planning is not False
            and agent.task_requires_validation
        )
        agent.task_max_steps = min(
            agent.configured_max_steps,
            agent.execution_policy.max_steps,
        )
        print(f"\n[执行模式] {agent.execution_policy.mode.value.upper()}")
        if agent.execution_route is not None:
            print(f"[路由] {agent.execution_route.reason}")
        return planning_enabled

    @staticmethod
    def _reset_task_services(agent) -> None:
        agent.progress.reset(new_task=True)
        agent.latest_progress_signal = None
        agent.finalization.reset()
        agent.step_evidence.reset()
        agent.plan_version = 0
        agent.rollback_revision = 0
        agent.validation_pipeline.reset()
        agent.checkpoint_manager.reset()
        agent.recovery.reset()
        agent.replan_count = 0
        agent.token_metrics.reset()
        agent.execution_metrics.reset(
            agent.execution_policy.mode.value,
            intent=agent.execution_route.intent.value,
        )
        agent.execution_metrics.record_routing(agent.task_router.last_telemetry)
        agent.requirements_extractor.reset()
        agent.runtime_control.reset(planning_active=False)
        agent.semantic_judge.reset()
        agent.regression_recovery_policy.reset()
        agent.task_steps_consumed = 0
        agent.concrete_blockers.clear()
        agent.edit_retry.reset()
        agent.latest_dependency_resolution = None
        agent.latest_symbol_recovery_paths = ()
        agent.completion_handler.reset()
        agent.context_budget.reset()
        agent.working_summary.reset()
        agent.git_awareness.reset_task()

    @staticmethod
    def _build_requirements_and_validation(agent, user_input: str) -> None:
        targets = tuple(getattr(agent.execution_route, "target_paths", ()) or ())
        agent.task_requirements = (
            agent.requirements_extractor.extract(
                user_input,
                mode=agent.execution_policy.mode,
                target_paths=targets,
                workspace=agent.workspace,
            )
            if agent.task_requires_validation
            else TaskRequirements()
        )
        agent.execution_metrics.record_requirements(
            agent.requirements_extractor.last_telemetry
        )
        impact = ChangeImpactResolver().resolve(agent.workspace_session, targets)
        agent.validation_pipeline.state.plan = ValidationPlanner().build(
            agent.task_requirements,
            profile=agent.workspace_session.profile,
            paths=targets,
            request=user_input,
            mode=agent.execution_policy.mode,
            impact=impact,
            available_capabilities=getattr(
                agent.registry,
                "available_capabilities",
                (),
            ),
        )
        agent.runtime_control.control_llm_calls = (
            agent.execution_metrics.routing_llm_calls
            + agent.execution_metrics.requirements_llm_calls
        )

    @staticmethod
    def _start_runtime(agent, user_input: str, planning_enabled: bool) -> None:
        agent.task_runtime = TaskRuntime()
        agent.task_state = agent.task_runtime.state
        agent.apply_runtime_event(
            RuntimeEventType.TASK_STARTED,
            mode=agent.execution_policy.mode,
            intent=agent.execution_route.intent,
            user_request=user_input,
            final_response_mode=agent.final_response_mode.value,
            target_paths=tuple(
                getattr(agent.execution_route, "target_paths", ()) or ()
            ),
            needs_plan=bool(getattr(agent.execution_route, "needs_plan", False)),
            planning_activated=planning_enabled,
            requirement_ids=tuple(
                item.id for item in agent.task_requirements.items
            ),
            satisfied_requirement_ids=(),
            remaining_steps=agent.task_max_steps,
        )

    @staticmethod
    def _prepare_repository_context(agent) -> None:
        agent._repo_map_initialized = False
        agent._repo_map_revision = None
        if agent.execution_policy.mode == ExecutionMode.FAST:
            agent.repo_map_text = "FAST 模式下已省略仓库地图。"
        else:
            agent._refresh_repo_map(force=True)

    @staticmethod
    def _create_initial_plan(agent, user_input: str, enabled: bool) -> None:
        if not enabled or agent.planner is None:
            return
        try:
            agent.active_plan = agent.planner.create_plan(
                user_input,
                max_agent_steps=agent.task_max_steps,
                max_plan_steps=agent.execution_policy.max_plan_steps,
                token_metrics=agent.token_metrics,
            )
            agent.apply_runtime_event(
                RuntimeEventType.PLAN_ACTIVATED,
                plan_revision=agent.plan_version,
            )
            agent._print_plan(agent.active_plan)
            initial = agent.reconcile_plan_progress()
            if initial["completed"]:
                print("\n[初始计划核对]")
                print(
                    "已满足的步骤："
                    + ", ".join(
                        str(item["step_id"])
                        for item in initial["completed"]
                    )
                )
        except Exception as exc:
            print(f"\n[规划失败] {type(exc).__name__}: {exc}")
