import json
import re

from .checkpoint import (
    CheckpointManager,
)
from .checkpoint_executor import (
    CheckpointingToolExecutor,
)
from .context_budget import (
    ContextBudget,
)
from .action_controller import (
    ActionController,
)
from .completion_policy import TaskCompletionPolicy
from .dependency_resolver import DependencyResolver
from .edit_retry import EditRetryPolicy
from .execution_mode import ExecutionMode
from .execution_policy import ExecutionPolicy, policy_for
from .finalization import FinalizationController
from .git_awareness import (
    GitAwareness,
    GitRepositoryInspector,
)
from .loop import (
    run_agent_loop,
)
from .metrics import (
    ExecutionMetrics,
    TokenMetrics,
)
from .progress import (
    ProgressController,
)
from .plan_progress import (
    PlanProgressReconciler,
)
from .recovery import (
    RecoveryController,
)
from .rollback import (
    RollbackEngine,
)
from .regression_policy import RegressionPolicy
from .safety import (
    SafetyPolicy,
)
from .safety_executor import (
    SafetyToolExecutor,
)
from .state import (
    AgentPlan,
)
from .step_evidence import StepEvidenceStore
from .task_router import TaskRouter
from .task_state import AgentPhase, TaskState
from .tool_executor import (
    ToolExecutor,
)
from .validation import (
    ValidationPipeline,
)
from .validation_selector import ValidationSelector
from .working_summary import (
    WorkingSummary,
)

from ..prompts.system import (
    build_fast_system_prompt,
    build_standard_system_prompt,
    build_system_prompt,
    build_turn_context,
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
        regression_policy: RegressionPolicy | None = None,
    ):

        self.llm = llm

        self.registry = registry

        self.status_interval_seconds = max(
            0.0,
            float(status_interval_seconds),
        )

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

        self.action_controller = ActionController()
        self.finalization = FinalizationController()
        self.step_evidence = StepEvidenceStore()
        self.completion_policy = TaskCompletionPolicy()
        self.execution_metrics = ExecutionMetrics()
        self.task_state = TaskState()
        self.edit_retry = EditRetryPolicy()
        self.dependency_resolver = DependencyResolver(self.workspace)
        self.validation_selector = ValidationSelector()
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
        state.mode = getattr(self.execution_policy, "mode", None)
        state.user_request = self.active_user_request or ""
        route = self.execution_route
        state.target_paths = tuple(getattr(route, "target_paths", ()) or ())
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
        return state

    def current_regression_requirement(self):
        policy = self.execution_policy
        if policy is None:
            from .regression_policy import RegressionRequirement

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

        self.active_user_request = (
            user_input
        )

        self.active_plan = None

        self.execution_policy = self.resolve_execution_policy(
            user_input,
            policy=policy,
        )
        self.task_requires_validation = bool(
            self.execution_route
            and self.execution_route.requires_coding_action
        )
        # FAST is structurally planless. A legacy caller cannot force the
        # Planner back into this mode with use_planning=True.
        planning_enabled = bool(
            self.execution_policy.use_plan
            and use_planning is not False
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

        self.finalization.reset()

        self.step_evidence.reset()

        self.plan_version = 0

        self.rollback_revision = 0

        self.validation_pipeline.reset()

        self.checkpoint_manager.reset()

        self.recovery.reset()

        self.replan_count = 0

        self.token_metrics.reset()

        self.execution_metrics.reset(self.execution_policy.mode.value)

        self.edit_retry.reset()

        self.task_state = TaskState(
            mode=self.execution_policy.mode,
            phase=AgentPhase.INSPECTING,
            user_request=user_input,
            target_paths=tuple(
                getattr(self.execution_route, "target_paths", ()) or ()
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
        return policy_for(self.execution_route.mode)

    def get_tool_schemas(self) -> list[dict]:
        """Expose only mode-relevant tools without mutating the Registry."""

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

        if (
            self.execution_policy is not None
            and self.execution_policy.compact_context
        ):
            return build_fast_system_prompt()
        if (
            self.execution_policy is not None
            and self.execution_policy.mode == ExecutionMode.STANDARD
        ):
            return build_standard_system_prompt()
        return build_system_prompt()

    # =========================================================
    # Dynamic Turn Context
    # =========================================================

    def _build_turn_context(
        self,
        plan=None,
        current_step=None,
        remaining_agent_steps: (
            int
            | None
        ) = None,
        **kwargs,
    ) -> str:

        # =====================================================
        # Fresh Repository Map
        # =====================================================

        compact_context = bool(
            self.execution_policy
            and self.execution_policy.compact_context
        )
        if not compact_context:
            self._refresh_repo_map()

        # =====================================================
        # Fresh Git State
        # =====================================================

        try:
            if compact_context:
                task_state = self.git_awareness.task_state()
                touched = task_state.agent_touched_files
                git_awareness_text = (
                    "Agent-touched files: "
                    + (", ".join(touched) if touched else "none yet")
                )
            else:
                self.git_awareness.refresh()
                git_awareness_text = self.git_awareness.render()
        except Exception as e:
            git_awareness_text = (
                "Git awareness unavailable: "
                f"{type(e).__name__}: {e}"
            )

        # =====================================================
        # Safety Context
        # =====================================================

        try:
            safety_policy_text = (
                "Use dedicated edit tools for file mutations. Unsafe "
                "destructive shell operations may be blocked."
                if compact_context
                else self.safety_policy.render()
            )
        except Exception as e:

            safety_policy_text = (
                "Safety policy unavailable: "
                f"{type(e).__name__}: "
                f"{e}"
            )

        # =====================================================
        # Plan
        # =====================================================

        plan_text = (
            self._plan_to_text(
                plan
            )
            if plan
            else (
                "No explicit plan."
            )
        )

        if current_step:

            current_step_text = (
                f"{current_step.id}. "
                f"{current_step.description}"
            )

        else:

            current_step_text = (
                "No active plan step."
            )

        # =====================================================
        # Build Context
        # =====================================================

        if compact_context:
            validation = self.validation_pipeline.state
            state = self.task_progress_state(remaining_agent_steps)
            registered = set(getattr(self.registry, "_tools", {}) or {})
            targets = tuple(
                getattr(self.execution_route, "target_paths", ()) or ()
            )
            selection = self.validation_selector.select(
                target_paths=targets,
                registered_tools=registered,
            )
            action_text = (
                self.action_controller.INSTRUCTION
                if self.action_controller.action_required
                else "Inspect minimally, then edit or validate."
            )
            return "\n\n".join(
                [
                    f"User request: {self.active_user_request or ''}",
                    f"Execution mode: FAST (no plan). Phase: {state.phase.value}.",
                    (
                        "Target paths: " + (", ".join(targets) if targets else "not explicit")
                    ),
                    f"Remaining agent steps: {remaining_agent_steps}",
                    (
                        "Validation state: "
                        f"revision={validation.edit_revision}, "
                        f"has_edit={validation.has_edit}, "
                        f"acceptance_passed={validation.acceptance_passed}."
                    ),
                    self.working_summary.render_relevant(targets, max_items=8)[-2000:],
                    (
                        f"Recommended acceptance validator: {selection.tool_name}"
                        + (f" for {selection.path}" if selection and selection.path else "")
                        if selection else "No dedicated acceptance validator selected."
                    ),
                    action_text,
                    safety_policy_text,
                ]
            ).strip() + "\n"

        return (
            build_turn_context(
                task_state_text=(
                    "Task state: "
                    f"mode={self.task_state.mode.value if self.task_state.mode else 'unknown'}, "
                    f"phase={self.task_state.phase.value}, "
                    f"edit_revision={self.task_state.edit_revision}, "
                    f"validation_revision={self.task_state.validation_revision}."
                ),
                plan_text=(
                    plan_text
                ),
                current_step_text=(
                    current_step_text
                ),
                remaining_agent_steps=(
                    remaining_agent_steps
                ),
                working_summary_text=(
                    self.working_summary.render_relevant(
                        tuple(getattr(self.execution_route, "target_paths", ()) or ()),
                        max_items=14,
                    )
                ),
                repo_map_text=(
                    self.repo_map_text[:2000]
                    if compact_context
                    else self.repo_map_text
                ),
                git_awareness_text=(
                    git_awareness_text
                ),
                safety_policy_text=(
                    safety_policy_text
                ),
            )
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
