import json
import io
import sys
import time
from contextlib import redirect_stdout

from .editing import (
    CheckpointManager,
    CheckpointingToolExecutor,
    EditRetryPolicy,
    RollbackCoordinator,
    RollbackEngine,
)
from .context import (
    ContextBudget,
)
from .progress import ActionController, FinalizationController
from .validation import (
    JudgeContextBuilder,
    RegressionPolicy,
    RegressionRecoveryPolicy,
    RelevantPathResolver,
    TaskCompletionPolicy,
    ValidationPipeline,
    ValidatorResolver,
    SemanticRegressionJudge,
)
from .dependency import DependencyResolver
from .routing import ExecutionMode, ExecutionPolicy, TaskIntent, TaskRouter, policy_for
from .runtime import (
    GitAwareness,
    GitRepositoryInspector,
    RuntimeTaskControl,
    ToolExecutor,
)
from .orchestration.loop import (
    run_agent_loop,
)
from .orchestration import (
    CompletionHandler,
    FinalResponseMode,
    ToolBatchRunner,
    TurnBuilder,
    ValidationOrchestrator,
    PlanOrchestrator,
)
from .observability import (
    ExecutionMetrics,
    OutputLevel,
    TokenMetrics,
)
from .progress import ProgressController
from .planning import (
    AgentPlan, PlanProgressReconciler, RequirementsExtractor,
    StepEvidenceStore, TaskRequirements,
)
from .progress import RecoveryController
from .safety import (
    SafetyPolicy,
    SafetyToolExecutor,
)
from .task_state import AgentPhase, RuntimeEventType, TaskRuntime, TaskState
from .validation.plan import ValidationPlanner
from .context.workspace_session import ChangeImpactResolver, WorkspaceSession
from .memory import (
    WorkingSummary,
)

class MiniCodexAgent:

    def __init__(
        self,
        llm,
        registry,
        planner=None,
        replanner=None,
        repo_map=None,
        max_steps: int = 20,
        max_step_attempts: int = 5,
        max_context_tokens: int = 64000,
        status_interval_seconds: float = 15.0,
        max_no_progress_steps: int = 5,
        task_router: TaskRouter | None = None,
        requirements_extractor: RequirementsExtractor | None = None,
        semantic_judge: SemanticRegressionJudge | None = None,
        regression_policy: RegressionPolicy | None = None,
        output_level: str | OutputLevel = OutputLevel.NORMAL,
    ):

        self.llm = llm

        self.registry = registry

        self.status_interval_seconds = max(
            0.0,
            float(status_interval_seconds),
        )
        self.output_level = OutputLevel.parse(output_level)
        self._normal_progress_stream = None

        # =====================================================
        # Shared Workspace
        # =====================================================

        self.workspace = (
            self._resolve_workspace(
                registry
            )
        )
        self.workspace_session = WorkspaceSession(self.workspace)

        # =====================================================
        # Git awareness
        # =====================================================

        self.git_inspector = (
            GitRepositoryInspector(
                workspace=(
                    self.workspace
                )
            )
        )

        self.git_awareness = (
            GitAwareness(
                inspector=(
                    self.git_inspector
                )
            )
        )

        # =====================================================
        # Safety and permissions
        # =====================================================

        self.safety_policy = (
            SafetyPolicy(
                workspace=(
                    self.workspace
                ),
                git_awareness=(
                    self.git_awareness
                ),
            )
        )

        # =====================================================
        # Behavioral Validation
        # =====================================================

        self.validation_pipeline = (
            ValidationPipeline()
        )

        # =====================================================
        # Checkpoint / Rollback
        # =====================================================

        self.checkpoint_manager = (
            CheckpointManager(
                workspace=(
                    self.workspace
                ),
                max_checkpoints=50,
            )
        )

        self.rollback_engine = (
            RollbackEngine(
                workspace=(
                    self.checkpoint_manager
                    .workspace
                ),
                checkpoint_manager=(
                    self.checkpoint_manager
                ),
            )
        )

        # =====================================================
        # Reliable Tool Execution
        # =====================================================

        base_tool_executor = (
            ToolExecutor(
                registry
            )
        )

        checkpoint_executor = (
            CheckpointingToolExecutor(
                executor=(
                    base_tool_executor
                ),
                checkpoint_manager=(
                    self.checkpoint_manager
                ),
                next_edit_revision=(
                    self._next_edit_revision
                ),
                on_successful_edit=(
                    self.git_awareness
                    .record_agent_edit
                ),
            )
        )

        # =====================================================
        # Safety boundary
        #
        # LLM
        #   ↓
        # Safety
        #   ↓
        # Checkpoint
        #   ↓
        # ToolExecutor
        # =====================================================

        self.tool_executor = (
            SafetyToolExecutor(
                registry=registry,
                executor=(
                    checkpoint_executor
                ),
                policy=(
                    self.safety_policy
                ),
            )
        )

        # =====================================================
        # Token Metrics
        # =====================================================

        self.token_metrics = (
            TokenMetrics()
        )

        # =====================================================
        # Context Budget
        # =====================================================

        self.context_budget = (
            ContextBudget(
                max_context_tokens=(
                    max_context_tokens
                )
            )
        )

        # =====================================================
        # Working Summary
        # =====================================================

        self.working_summary = (
            WorkingSummary(
                max_items=30
            )
        )

        # =====================================================
        # Repository Map
        # =====================================================

        self.repo_map = (
            repo_map
        )

        self.repo_map_text = (
            "Repository map unavailable."
        )

        # =====================================================
        # Planning
        # =====================================================

        self.planner = (
            planner
        )

        self.replanner = (
            replanner
        )

        self.max_steps = (
            max_steps
        )
        self.configured_max_steps = max(1, int(max_steps))
        self.task_max_steps = self.configured_max_steps

        self.max_step_attempts = (
            max_step_attempts
        )

        # =====================================================
        # Active Task State
        # =====================================================

        self.active_plan: (
            AgentPlan
            | None
        ) = None

        self.active_user_request: (
            str
            | None
        ) = None

        self.task_router = task_router or TaskRouter()
        self.requirements_extractor = requirements_extractor or RequirementsExtractor()
        self.task_requirements = TaskRequirements()
        self.runtime_control = RuntimeTaskControl()
        self.semantic_judge = semantic_judge or SemanticRegressionJudge()
        self.judge_context_builder = JudgeContextBuilder()
        self.regression_recovery_policy = RegressionRecoveryPolicy()
        self.task_steps_consumed = 0
        self.concrete_blockers: list[str] = []
        self.regression_policy = regression_policy or RegressionPolicy()
        self.execution_route = None
        self.execution_policy: ExecutionPolicy | None = None
        self.task_requires_validation = True
        self.plan_version = 0
        self.rollback_revision = 0

        # =====================================================
        # Progress
        # =====================================================

        self.progress = (
            ProgressController(
                max_same_tool_repeats=2,
                max_validation_no_progress=2,
            )
        )
        self.latest_progress_signal = None

        self.action_controller = ActionController(registry)
        self.finalization = FinalizationController()
        self.step_evidence = StepEvidenceStore()
        self.completion_policy = TaskCompletionPolicy()
        self.execution_metrics = ExecutionMetrics()
        self.task_runtime = TaskRuntime()
        self.task_state = self.task_runtime.state
        self.edit_retry = EditRetryPolicy()
        self.dependency_resolver = DependencyResolver(self.workspace)
        self.latest_dependency_resolution = None
        self.latest_symbol_recovery_paths: tuple[str, ...] = ()
        self.relevant_path_resolver = RelevantPathResolver(self.workspace)
        self.validator_resolver = ValidatorResolver(self.workspace, test_index=self.workspace_session.test_index)
        for tool in getattr(self.registry, "_tools", {}).values():
            if hasattr(tool, "symbol_index"):
                tool.symbol_index = self.workspace_session.symbol_index
        self.completion_handler = CompletionHandler()
        self.turn_builder = TurnBuilder()
        self.tool_batch_runner = ToolBatchRunner()
        self.rollback_coordinator = RollbackCoordinator()
        self.validation_orchestrator = ValidationOrchestrator(self.rollback_coordinator)
        self.plan_orchestrator = PlanOrchestrator()
        self.final_response_mode = FinalResponseMode.TASK_REPORT
        self.replan_count = 0

        self.plan_progress_reconciler = (
            PlanProgressReconciler(
                workspace=self.workspace
            )
        )

        # =====================================================
        # Recovery
        # =====================================================

        self.recovery = (
            RecoveryController(
                max_recovery_level=3
            )
        )

        self._repo_map_revision: int | None = None
        self._repo_map_initialized = False

    # =========================================================
    # Workspace Resolution
    # =========================================================

    @staticmethod
    def _resolve_workspace(
        registry,
    ):
        """
        Resolve the shared workspace from registered tools.
        """

        tools = getattr(
            registry,
            "_tools",
            {},
        )

        for tool in (
            tools.values()
        ):

            workspace = getattr(
                tool,
                "workspace",
                None,
            )

            if (
                workspace
                is not None
            ):

                return workspace

        return "."

    # =========================================================
    # Next Edit Revision
    # =========================================================

    def _next_edit_revision(
        self,
    ) -> int:

        return (
            self.validation_pipeline
            .state
            .edit_revision
            + 1
        )

    def apply_runtime_event(self, kind: RuntimeEventType, **data) -> TaskState:
        """Apply one fact to the canonical task state."""

        state = self.task_runtime.emit(kind, **data)
        self.task_state = state
        return state

    def ensure_runtime_started(self, user_request: str = "") -> TaskState:
        """Initialize canonical state for direct loop/test integrations."""

        if self.task_state.run_id:
            return self.task_state
        validation = self.validation_pipeline.state
        latest = validation.latest_evidence
        route = self.execution_route
        policy = self.execution_policy
        return self.apply_runtime_event(
            RuntimeEventType.TASK_STARTED,
            mode=getattr(policy, "mode", None),
            intent=getattr(route, "intent", TaskIntent.MODIFY),
            user_request=user_request or self.active_user_request or "",
            final_response_mode=self.final_response_mode.value,
            target_paths=tuple(getattr(route, "target_paths", ()) or ()),
            needs_plan=bool(getattr(route, "needs_plan", False)),
            planning_activated=self.active_plan is not None,
            requirement_ids=tuple(item.id for item in self.task_requirements.items),
            satisfied_requirement_ids=tuple(
                item.id for item in self.task_requirements.items if item.satisfied
            ),
            remaining_steps=self.task_max_steps,
            edit_revision=validation.edit_revision,
            validation_revision=getattr(validation, "evidence_sequence", 0),
            has_edit=validation.has_edit,
            acceptance_passed=validation.acceptance_passed,
            relevant_validation_passed=validation.targeted_passed,
            full_validation_passed=validation.full_passed,
            latest_validation_outcome=getattr(latest, "outcome", None),
            active_evidence_edit_revision=getattr(latest, "edit_revision", None),
        )

    def task_progress_state(self, remaining_steps: int | None = None) -> TaskState:
        if remaining_steps is not None:
            self.apply_runtime_event(
                RuntimeEventType.BUDGET_UPDATED,
                consumed_steps=self.task_steps_consumed,
                remaining_steps=remaining_steps,
            )
        return self.task_state

    def refresh_runtime_context(self) -> TaskState:
        """Update derived path scope at a deliberate context boundary."""

        return self.apply_runtime_event(
            RuntimeEventType.CONTEXT_UPDATED,
            relevant_paths=self.relevant_path_resolver.resolve(self).paths,
        )

    def sync_requirements_state(self) -> TaskState:
        return self.apply_runtime_event(
            RuntimeEventType.REQUIREMENTS_UPDATED,
            requirement_ids=tuple(item.id for item in self.task_requirements.items),
            satisfied_requirement_ids=tuple(
                item.id for item in self.task_requirements.items if item.satisfied
            ),
        )

    def sync_plan_state(self, *, superseded_steps: tuple[int, ...] = ()) -> TaskState:
        completed = tuple(
            step.id
            for step in (self.active_plan.all_steps() if self.active_plan is not None else ())
            if getattr(step.status, "value", step.status) == "completed"
        )
        return self.apply_runtime_event(
            RuntimeEventType.PLAN_RECONCILED,
            planning_activated=self.active_plan is not None,
            plan_revision=self.plan_version,
            completed_steps=completed,
            superseded_steps=superseded_steps,
        )

    def current_regression_requirement(self):
        policy = self.execution_policy
        if policy is None:
            from .validation import RegressionRequirement

            return RegressionRequirement.REQUIRED

        touched = ()
        try:
            touched = self.git_awareness.task_state().agent_touched_files
        except Exception:
            pass
        if not touched and self.execution_route is not None:
            touched = self.execution_route.target_paths

        return self.regression_policy.requirement_for(
            mode=policy.mode,
            changed_paths=touched,
            default=policy.regression_requirement,
        )

    # =========================================================
    # Main Entry
    # =========================================================

    def run(
        self,
        user_input: str,
        use_planning: bool | None = None,
        policy: ExecutionPolicy | None = None,
    ) -> str:
        started = time.monotonic()
        if self.output_level in {OutputLevel.VERBOSE, OutputLevel.DEBUG}:
            try:
                return self._run_impl(user_input, use_planning=use_planning, policy=policy)
            finally:
                self.execution_metrics.duration_seconds = time.monotonic() - started
        # Legacy control-plane diagnostics remain available in verbose/debug.
        # Normal product use exposes only small user-facing action events.
        self._normal_progress_stream = sys.stdout
        try:
            with redirect_stdout(io.StringIO()):
                return self._run_impl(user_input, use_planning=use_planning, policy=policy)
        finally:
            self.execution_metrics.duration_seconds = time.monotonic() - started
            self._normal_progress_stream = None

    def emit_normal_progress(self, message: str) -> None:
        stream = self._normal_progress_stream
        if stream is not None:
            print(str(message).strip(), file=stream, flush=True)

    def refresh_workspace_facts(self):
        session = self.workspace_session
        external_candidate = session._fingerprint is not None
        owned_dirty = bool(getattr(session, "_dirty_paths", ()))
        if session.refresh(periodic=True) and external_candidate and not owned_dirty and self.task_state.run_id:
            revision = self.validation_pipeline.record_edit(owned=False)
            self.task_requirements.invalidate_revision(revision)
            self.working_summary.advance_revision(revision)
            self.apply_runtime_event(RuntimeEventType.WORKSPACE_CHANGED, edit_revision=revision,
                                     paths=session.changed_paths)
            self.sync_requirements_state()
            self._repo_map_initialized = False
            self._repo_map_revision = None

    def undo_task(self):
        """Explicit user-facing undo; never invoked by ordinary validation failure."""
        result = self.rollback_engine.undo_task()
        if result.data.get("restored_paths"):
            revision = self.validation_pipeline.record_edit()
            self.task_requirements.invalidate_revision(revision)
            self.apply_runtime_event(RuntimeEventType.ROLLBACK_APPLIED, edit_revision=revision,
                                     restored_paths=tuple(result.data["restored_paths"]))
            self.sync_requirements_state()
            for path in result.data["restored_paths"]:
                self.workspace_session.invalidate(path)
        return result

    def check_completion_after_batch(self):
        """Completion ownership stays with CompletionHandler, not batch protocol."""
        return self.completion_handler.check_after_batch(self)

    def _run_impl(
        self,
        user_input: str,
        use_planning: bool | None = None,
        policy: ExecutionPolicy | None = None,
    ) -> str:

        self.active_user_request = (
            user_input
        )
        self.workspace_session.refresh(full=True)

        self.active_plan = None

        self.execution_policy = self.resolve_execution_policy(
            user_input,
            policy=policy,
        )
        self.task_requires_validation = bool(
            self.execution_route and self.execution_route.intent == TaskIntent.MODIFY
        )
        self.safety_policy.begin_task(
            user_input,
            routed_intent=getattr(self.execution_route, "intent", None),
        )
        self.final_response_mode = self.completion_handler.response_mode(self)
        planning_enabled = bool(
            self.execution_policy.use_plan
            and use_planning is not False
            and self.task_requires_validation
        )
        self.task_max_steps = min(
            self.configured_max_steps,
            self.execution_policy.max_steps,
        )
        print(
            f"\n[Execution Mode] {self.execution_policy.mode.value.upper()}"
        )
        if self.execution_route is not None:
            print(f"[Routing] {self.execution_route.reason}")

        # =====================================================
        # Reset Task State
        # =====================================================

        self.progress.reset(
            new_task=True
        )
        self.latest_progress_signal = None

        self.finalization.reset()

        self.step_evidence.reset()

        self.plan_version = 0

        self.rollback_revision = 0

        self.validation_pipeline.reset()

        self.checkpoint_manager.reset()

        self.recovery.reset()

        self.replan_count = 0

        self.token_metrics.reset()

        self.execution_metrics.reset(
            self.execution_policy.mode.value,
            intent=self.execution_route.intent.value,
        )
        self.execution_metrics.record_routing(self.task_router.last_telemetry)

        self.requirements_extractor.reset()
        self.task_requirements = (
            self.requirements_extractor.extract(
                user_input,
                mode=self.execution_policy.mode,
                target_paths=getattr(self.execution_route, "target_paths", ()),
            )
            if self.task_requires_validation
            else TaskRequirements()
        )
        self.execution_metrics.record_requirements(
            self.requirements_extractor.last_telemetry
        )
        change_impact = ChangeImpactResolver().resolve(
            self.workspace_session, getattr(self.execution_route, "target_paths", ())
        )
        self.validation_pipeline.state.plan = ValidationPlanner().build(
            self.task_requirements, profile=self.workspace_session.profile,
            paths=getattr(self.execution_route, "target_paths", ()), request=user_input,
            mode=self.execution_policy.mode, impact=change_impact,
            available_capabilities=getattr(self.registry, "available_capabilities", ()))
        self.runtime_control.reset(planning_active=False)
        self.runtime_control.control_llm_calls = (
            self.execution_metrics.routing_llm_calls
            + self.execution_metrics.requirements_llm_calls
        )
        self.semantic_judge.reset()
        self.regression_recovery_policy.reset()
        self.task_steps_consumed = 0
        self.concrete_blockers.clear()

        self.edit_retry.reset()

        self.latest_dependency_resolution = None

        self.latest_symbol_recovery_paths = ()

        self.completion_handler.reset()

        self.task_runtime = TaskRuntime()
        self.task_state = self.task_runtime.state
        self.apply_runtime_event(
            RuntimeEventType.TASK_STARTED,
            mode=self.execution_policy.mode,
            intent=self.execution_route.intent,
            user_request=user_input,
            final_response_mode=self.final_response_mode.value,
            target_paths=tuple(getattr(self.execution_route, "target_paths", ()) or ()),
            needs_plan=bool(getattr(self.execution_route, "needs_plan", False)),
            planning_activated=planning_enabled,
            requirement_ids=tuple(item.id for item in self.task_requirements.items),
            satisfied_requirement_ids=tuple(
                item.id for item in self.task_requirements.items if item.satisfied
            ),
            remaining_steps=self.task_max_steps,
        )

        self.context_budget.reset()

        self.working_summary.reset()

        # =====================================================
        # Task-Start Git Baseline
        # =====================================================

        self.git_awareness.reset_task()

        # =====================================================
        # Initial Repository Map
        # =====================================================

        self._repo_map_initialized = False
        self._repo_map_revision = None
        fast_mode = self.execution_policy.mode == ExecutionMode.FAST
        if fast_mode:
            self.repo_map_text = "Repository map omitted in FAST mode."
        else:
            self._refresh_repo_map(force=True)

        # =====================================================
        # Initial Plan
        # =====================================================

        if (
            planning_enabled
            and self.planner
        ):

            try:

                self.active_plan = (
                    self.planner
                    .create_plan(
                        user_input,
                        max_agent_steps=(
                            self.task_max_steps
                        ),
                        max_plan_steps=(
                            self.execution_policy.max_plan_steps
                        ),
                        token_metrics=(
                            self.token_metrics
                        ),
                    )
                )

                self.apply_runtime_event(
                    RuntimeEventType.PLAN_ACTIVATED,
                    plan_revision=self.plan_version,
                )

                self._print_plan(
                    self.active_plan
                )

                initial = self.reconcile_plan_progress()
                if initial["completed"]:
                    print("\n[Initial Plan Reconciliation]")
                    print(
                        "Already-satisfied steps: "
                        + ", ".join(
                            str(item["step_id"])
                            for item in initial["completed"]
                        )
                    )

            except Exception as e:

                print(
                    f"\n[Planning Failed] "
                    f"{type(e).__name__}: "
                    f"{e}"
                )

        # =====================================================
        # Agent Loop
        # =====================================================

        self.runtime_control.planning_activated = self.active_plan is not None
        self.refresh_runtime_context()
        self.action_controller.reset(self.task_progress_state())

        return (
            run_agent_loop(
                self,
                user_input,
            )
        )

    def resolve_execution_policy(
        self,
        user_input: str,
        *,
        policy: ExecutionPolicy | None = None,
    ) -> ExecutionPolicy:
        if policy is not None:
            self.execution_route = self.task_router.route(user_input)
            return policy

        self.execution_route = self.task_router.route(user_input)
        return policy_for(
            self.execution_route.mode,
            needs_plan=getattr(self.execution_route, "needs_plan", None),
        )

    def activate_late_plan(self, *, reason: str) -> bool:
        """Monotonically activate planning when runtime scope disproves direct execution."""
        if self.active_plan is not None or self.runtime_control.planning_activated:
            return False
        if self.planner is None or not self.task_requires_validation:
            return False
        try:
            self.active_plan = self.planner.create_plan(
                self.active_user_request or "",
                max_agent_steps=self.task_max_steps,
                max_plan_steps=max(1, self.execution_policy.max_plan_steps),
                token_metrics=self.token_metrics,
            )
        except Exception:
            return False
        self.runtime_control.planning_activated = True
        self.runtime_control.late_plan_activations += 1
        self.execution_metrics.late_plan_activations = self.runtime_control.late_plan_activations
        self.plan_version += 1
        self.apply_runtime_event(
            RuntimeEventType.PLAN_ACTIVATED,
            plan_revision=self.plan_version,
        )
        self.working_summary.add(f"Late planning activated: {reason}")
        self._print_plan(self.active_plan)
        return True

    def get_tool_schemas(self) -> list[dict]:
        """Expose only mode-relevant tools without mutating the Registry."""

        intent = getattr(self.execution_route, "intent", TaskIntent.MODIFY)
        if intent == TaskIntent.INFORMATIONAL:
            # File-specific explanations may inspect the workspace; general
            # questions do not need tool access.
            allowed_capabilities = (
                {"filesystem.read", "code.search"}
                if getattr(self.execution_route, "target_paths", ())
                else set()
            )
            return self._schemas_for_capabilities(allowed_capabilities) if allowed_capabilities else []
        if intent == TaskIntent.INSPECT_ONLY:
            inspect_capabilities = {
                "filesystem.read", "code.search", "git.inspect", "test.run",
                "validation.static_web", "validation.browser", "process.run",
            }
            schemas = self._schemas_for_capabilities(inspect_capabilities)
        else:
            schemas = self.registry.get_schemas()
        policy = self.execution_policy
        allowed = getattr(policy, "exposed_tool_names", None)
        if allowed is None:
            return schemas
        allowed_capabilities = set().union(*(self.registry.capabilities_for(name)
                                              for name in allowed if name in getattr(self.registry, "_tools", {})))
        return [
            schema
            for schema in schemas
            if schema.get("function", {}).get("name") in allowed
            or (schema.get("function", {}).get("name") in getattr(self.registry, "_tools", {})
                and bool(self.registry.capabilities_for(schema["function"]["name"]) & allowed_capabilities))
        ]

    def _schemas_for_capabilities(self, capabilities: set[str]) -> list[dict]:
        """Filter through tool-owned capability declarations."""
        try:
            return self.registry.get_schemas(capabilities=capabilities)
        except TypeError:
            # Minimal test/third-party registries may predate capability filtering.
            return self.registry.get_schemas()

    # =========================================================
    # Repository Map Refresh
    # =========================================================

    def _refresh_repo_map(
        self,
        *,
        force: bool = False,
    ) -> None:

        if (
            self.repo_map
            is None
        ):

            self.repo_map_text = (
                "Repository map unavailable."
            )

            return

        policy = self.execution_policy
        current_revision = self.validation_pipeline.state.edit_revision
        refresh_policy = getattr(
            policy,
            "repo_map_refresh_policy",
            "every_turn",
        )

        if (
            not force
            and self._repo_map_initialized
            and refresh_policy != "every_turn"
            and self._repo_map_revision == current_revision
        ):
            return

        try:

            self.repo_map_text = (
                self.repo_map
                .build()
            )
            self._repo_map_initialized = True
            self._repo_map_revision = current_revision

        except Exception as e:

            self.repo_map_text = (
                "Repository map unavailable: "
                f"{type(e).__name__}: "
                f"{e}"
            )

    def reconcile_plan_progress(self) -> dict:
        return self.plan_orchestrator.reconcile_progress(self)

    def replan(self, reason: str) -> dict:
        return self.plan_orchestrator.replan_task(self, reason)

    # =========================================================
    # System Prompt
    # =========================================================

    def _build_system_prompt(
        self,
        **kwargs,
    ) -> str:
        return self.turn_builder.prompt_builder.build(self, **kwargs)

    # =========================================================
    # Dynamic Turn Context
    # =========================================================

    def _build_turn_context(
        self,
        plan=None,
        current_step=None,
        remaining_agent_steps: int | None = None,
        **kwargs,
    ) -> str:
        del kwargs
        return self.turn_builder.context_builder.build(
            self,
            current_plan_step=current_step,
            remaining_agent_steps=(
                self.task_state.remaining_steps
                if remaining_agent_steps is None
                else remaining_agent_steps
            ),
        )

    # =========================================================
    # Plan → Text
    # =========================================================

    def _plan_to_text(
        self,
        plan: AgentPlan,
    ) -> str:

        return "\n".join(
            (
                f"{step.id}. "
                f"[{step.status.value}] "
                f"{step.description} "
                f"(criteria="
                f"{self._criteria_text(step)}, "
                f"failures="
                f"{step.attempts})"
            )
            for step
            in plan.all_steps()
        )

    @staticmethod
    def _criteria_text(step) -> str:
        criteria = getattr(
            step,
            "acceptance_criteria",
            [],
        )

        if not criteria:
            if getattr(
                step,
                "requires_semantic_completion",
                False,
            ):
                return (
                    "semantic-only; broad step requires "
                    "explicit completion"
                )
            return "semantic-only"

        return json.dumps(
            criteria,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    # =========================================================
    # Print Plan
    # =========================================================

    def _print_plan(
        self,
        plan: AgentPlan,
    ) -> None:

        print(
            f"\n[Plan] "
            f"{plan.goal}"
        )

        for step in (
            plan.all_steps()
        ):

            print(
                f"{step.id}. "
                f"[{step.status.value}] "
                f"{step.description} "
                f"(failures="
                f"{step.attempts})"
            )

            for warning in getattr(
                step,
                "quality_warnings",
                [],
            ):
                print(
                    f"   [Plan Quality] {warning}"
                )
