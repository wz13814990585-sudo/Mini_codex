import json
import re
import io
import sys
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
    ValidationSelector,
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
from .task_state import AgentPhase, TaskState
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

        # =====================================================
        # Stage 11 Git Awareness
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
        # Stage 12 Safety / Permission
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
        # Stage 12 Safety Boundary
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

        self.action_controller = ActionController()
        self.finalization = FinalizationController()
        self.step_evidence = StepEvidenceStore()
        self.completion_policy = TaskCompletionPolicy()
        self.execution_metrics = ExecutionMetrics()
        self.task_state = TaskState()
        self.edit_retry = EditRetryPolicy()
        self.dependency_resolver = DependencyResolver(self.workspace)
        self.latest_dependency_resolution = None
        self.latest_symbol_recovery_paths: tuple[str, ...] = ()
        self.relevant_path_resolver = RelevantPathResolver(self.workspace)
        self.validation_selector = ValidationSelector(self.workspace)
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

    def task_progress_state(self, remaining_steps: int | None = None) -> TaskState:
        plan = self.active_plan
        validation_state = self.validation_pipeline.state
        completed = tuple(
            step.id
            for step in (plan.all_steps() if plan is not None else [])
            if getattr(step.status, "value", step.status) == "completed"
        )
        state = self.task_state
        route = self.execution_route
        state.mode = getattr(self.execution_policy, "mode", None)
        state.intent = getattr(route, "intent", TaskIntent.MODIFY)
        state.needs_plan = bool(getattr(route, "needs_plan", False))
        state.planning_activated = self.active_plan is not None
        state.user_request = self.active_user_request or ""
        state.final_response_mode = self.final_response_mode.value
        state.target_paths = tuple(getattr(route, "target_paths", ()) or ())
        state.relevant_paths = self.relevant_path_resolver.resolve(self).paths
        state.edit_revision = validation_state.edit_revision
        state.validation_revision = getattr(validation_state, "evidence_sequence", 0)
        state.rollback_revision = self.rollback_revision
        state.plan_revision = self.plan_version
        state.completed_plan_steps = completed
        state.has_edit = validation_state.has_edit
        state.acceptance_passed = validation_state.acceptance_passed
        state.relevant_validation_passed = validation_state.targeted_passed
        state.full_validation_passed = validation_state.full_passed
        state.consecutive_inspections = self.action_controller.consecutive_inspections
        state.consecutive_no_state_change = self.action_controller.consecutive_no_state_change
        if remaining_steps is not None:
            state.remaining_steps = max(0, int(remaining_steps))
        latest = validation_state.latest_evidence
        state.latest_validation_outcome = latest.outcome if latest is not None else None
        state.active_evidence_edit_revision = (
            getattr(latest, "edit_revision", None) if latest is not None else None
        )
        state.requirement_ids = tuple(item.id for item in self.task_requirements.items)
        state.satisfied_requirement_ids = tuple(
            item.id for item in self.task_requirements.items if item.satisfied
        )
        return state

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
        if self.output_level in {OutputLevel.VERBOSE, OutputLevel.DEBUG}:
            return self._run_impl(user_input, use_planning=use_planning, policy=policy)
        # Legacy control-plane diagnostics remain available in verbose/debug.
        # Normal product use exposes only small user-facing action events.
        self._normal_progress_stream = sys.stdout
        try:
            with redirect_stdout(io.StringIO()):
                return self._run_impl(user_input, use_planning=use_planning, policy=policy)
        finally:
            self._normal_progress_stream = None

    def emit_normal_progress(self, message: str) -> None:
        stream = self._normal_progress_stream
        if stream is not None:
            print(str(message).strip(), file=stream, flush=True)

    def _run_impl(
        self,
        user_input: str,
        use_planning: bool | None = None,
        policy: ExecutionPolicy | None = None,
    ) -> str:

        self.active_user_request = (
            user_input
        )

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

        self.task_state = TaskState(
            mode=self.execution_policy.mode,
            intent=self.execution_route.intent,
            phase=AgentPhase.INSPECTING,
            user_request=user_input,
            final_response_mode=self.final_response_mode.value,
            target_paths=tuple(
                getattr(self.execution_route, "target_paths", ()) or ()
            ),
            needs_plan=bool(getattr(self.execution_route, "needs_plan", False)),
            planning_activated=planning_enabled,
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
        return [
            schema
            for schema in schemas
            if schema.get("function", {}).get("name") in allowed
        ]

    def _schemas_for_capabilities(self, capabilities: set[str]) -> list[dict]:
        """Filter capabilities, with a fallback for minimal registries."""

        try:
            return self.registry.get_schemas(capabilities=capabilities)
        except TypeError:
            from ..tools.registry import ToolRegistry

            schemas = self.registry.get_schemas()
            fallback = getattr(ToolRegistry, "_NAME_CAPABILITIES", {})
            return [
                schema
                for schema in schemas
                if set(fallback.get(schema.get("function", {}).get("name"), ()))
                & capabilities
            ]

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

    # =========================================================
    # Complete Plan Step
    # =========================================================

    def reconcile_plan_progress(
        self,
    ) -> dict:
        """Complete only sequential steps with proven predicates."""

        completed = []
        evaluations = []

        while self.active_plan is not None:
            step = self.active_plan.get_current_step()
            if step is None:
                break

            evaluation = (
                self.plan_progress_reconciler
                .evaluate_step(
                    step,
                    validation_state=(
                        self.validation_pipeline.state
                    ),
                )
            )
            evaluations.append(
                {
                    "step_id": step.id,
                    "machine_checkable": (
                        evaluation.machine_checkable
                    ),
                    "satisfied": evaluation.satisfied,
                }
            )

            if not evaluation.satisfied:
                break

            result = self.complete_plan_step()
            if not result.get("completed"):
                break

            completed.append(
                {
                    "step_id": result["step_id"],
                    "step_description": result[
                        "step_description"
                    ],
                }
            )

        return {
            "completed": completed,
            "evaluations": evaluations,
        }

    def complete_plan_step(
        self,
    ) -> dict:

        if (
            self.active_plan
            is None
        ):

            return {
                "completed": False,
                "step_id": None,
                "step_description": None,
                "message": (
                    "No active plan."
                ),
            }

        current = self.active_plan.get_current_step()

        if current is not None and self.execution_policy is not None:
            criteria = list(current.acceptance_criteria or [])
            if criteria:
                evaluation = self.plan_progress_reconciler.evaluate_step(
                    current,
                    validation_state=self.validation_pipeline.state,
                )
                if not evaluation.satisfied:
                    return {
                        "completed": False,
                        "step_id": current.id,
                        "step_description": current.description,
                        "failure_type": "plan_step_criteria_not_satisfied",
                        "message": (
                            "The current plan step has machine-checkable "
                            "criteria that are not yet satisfied."
                        ),
                    }
            elif getattr(current, "requires_semantic_completion", False) and not self.step_evidence.has_validation(
                step_id=current.id,
                edit_revision=self.validation_pipeline.state.edit_revision,
            ):
                return {
                    "completed": False,
                    "step_id": current.id,
                    "step_description": current.description,
                    "failure_type": "broad_semantic_step_without_acceptance_evidence",
                    "message": (
                        "A broad semantic plan step requires current-revision "
                        "acceptance evidence; a file edit alone is insufficient."
                    ),
                }
            elif not self.step_evidence.has_sufficient(
                step_id=current.id,
                edit_revision=self.validation_pipeline.state.edit_revision,
            ):
                return {
                    "completed": False,
                    "step_id": current.id,
                    "step_description": current.description,
                    "failure_type": (
                        "semantic_step_completion_without_fresh_evidence"
                    ),
                    "message": (
                        "Semantic plan completion was rejected because no "
                        "sufficient fresh implementation/validation evidence "
                        "exists for the current revision."
                    ),
                }

        step = self.active_plan.complete_current_step()

        if (
            step
            is None
        ):

            return {
                "completed": False,
                "step_id": None,
                "step_description": None,
                "message": (
                    "No active plan step."
                ),
            }

        self.recovery.mark_progress()

        self.progress.reset()

        self.plan_version += 1

        self._print_plan(
            self.active_plan
        )

        return {
            "completed": True,
            "step_id": (
                step.id
            ),
            "step_description": (
                step.description
            ),
            "message": (
                f"Completed plan step "
                f"{step.id}: "
                f"{step.description}"
            ),
        }

    # =========================================================
    # Replan
    # =========================================================

    def replan(
        self,
        reason: str,
    ) -> dict:

        if (
            self.active_plan
            is None
        ):

            return {
                "replanned": False,
                "reason": reason,
                "failure_reason": (
                    "No active plan to revise."
                ),
                "message": (
                    "No active plan to revise."
                ),
            }

        if (
            self.execution_policy is not None
            and not self.execution_policy.enable_replan
        ):
            return {
                "replanned": False,
                "reason": reason,
                "failure_reason": "Replanning is disabled by execution policy.",
                "message": "Replanning is disabled in FAST mode.",
            }

        if (
            self.execution_policy is not None
            and self.replan_count >= self.execution_policy.max_replans
        ):
            return {
                "replanned": False,
                "reason": reason,
                "failure_reason": "Replan budget exhausted.",
                "message": "The execution policy replan budget is exhausted.",
            }

        if (
            self.replanner
            is None
        ):

            return {
                "replanned": False,
                "reason": reason,
                "failure_reason": (
                    "No replanner configured."
                ),
                "message": (
                    "No replanner configured."
                ),
            }

        if (
            self.active_user_request
            is None
        ):

            return {
                "replanned": False,
                "reason": reason,
                "failure_reason": (
                    "Original request unavailable."
                ),
                "message": (
                    "Original request unavailable."
                ),
            }

        try:

            new_plan = (
                self.replanner
                .replan(
                    user_request=(
                        self.active_user_request
                    ),
                    current_plan=(
                        self.active_plan
                    ),
                    reason=reason,
                    token_metrics=(
                        self.token_metrics
                    ),
                )
            )

        except Exception as e:

            error_message = (
                "Replanning failed: "
                f"{type(e).__name__}: "
                f"{e}"
            )

            return {
                "replanned": False,
                "reason": reason,
                "failure_reason": (
                    error_message
                ),
                "message": (
                    error_message
                ),
            }

        self.active_plan = (
            new_plan
        )

        self.replan_count += 1

        self.plan_version += 1

        self.progress.reset()

        print(
            "\n[Replanned]"
        )

        print(
            f"Reason: "
            f"{reason}"
        )

        self._print_plan(
            self.active_plan
        )

        return {
            "replanned": True,
            "reason": reason,
            "failure_reason": None,
            "message": (
                "Plan successfully revised. "
                "Continue execution using "
                "the new plan."
            ),
        }

    # =========================================================
    # Step Type Detection
    # =========================================================

    def _step_likely_requires_edit(
        self,
        current_step,
    ) -> bool:

        if (
            current_step
            is None
        ):

            return False

        text = (
            current_step
            .description
        )

        lowered = (
            text.lower()
        )

        english_keywords = (
            "fix",
            "modify",
            "change",
            "implement",
            "add",
            "update",
            "remove",
            "refactor",
            "rewrite",
            "replace",
            "create",
            "write",
        )

        chinese_keywords = (
            "修复",
            "修改",
            "实现",
            "增加",
            "添加",
            "更新",
            "删除",
            "重构",
            "新建",
            "重写",
            "替换",
            "写入",
            "编写",
        )

        if any(
            keyword in text
            for keyword
            in chinese_keywords
        ):

            return True

        return any(
            re.search(
                rf"\b{keyword}\b",
                lowered,
            )
            for keyword
            in english_keywords
        )

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
        return self.turn_builder.context_builder.build_detailed(
            self,
            plan=plan,
            current_step=current_step,
            remaining_agent_steps=remaining_agent_steps,
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
