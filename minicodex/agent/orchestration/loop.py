"""Agent execution loop."""

import threading
import time

from ..completion import (
    TaskOutcome,
)
from .message_protocol import (
    close_tool_batch_before_control_transition,
    validate_tool_message_protocol,
)
from .tool_batch import commit_batch_transition
from .orchestration_transitions import (
    record_task_outcome,
)


# =============================================================
# Constants
# =============================================================


INCOMPLETE_PLAN_REMINDER = (
    "The implementation plan is not finished. "
    "Continue working on the current plan step. "
    "Call complete_plan_step only after that step "
    "is actually done. Do not give a final answer yet."
)


EDIT_TOOL_NAMES = {
    "patch_file",
    "replace_lines",
    "replace_symbol",
    "write_file",
}


def _chat_with_heartbeat(
    agent,
    *,
    messages: list,
    tools: list,
):
    """Keep the synchronous CLI visibly alive during slow LLM calls."""

    # Provider protocol corruption is a Harness bug. Detect it locally
    # before making a network request that would otherwise fail with 400.
    validate_tool_message_protocol(messages)

    interval = max(
        0.0,
        float(
            getattr(
                agent,
                "status_interval_seconds",
                15.0,
            )
        ),
    )

    print("\n[LLM] Waiting for model response...")

    if interval == 0:
        return agent.llm.chat(
            messages=messages,
            tools=tools,
        )

    stopped = threading.Event()
    started = time.monotonic()

    def report_wait() -> None:

        while not stopped.wait(interval):
            elapsed = int(time.monotonic() - started)
            print(
                "[LLM] Still working "
                f"({elapsed}s elapsed)...",
                flush=True,
            )

    reporter = threading.Thread(
        target=report_wait,
        daemon=True,
    )
    reporter.start()

    try:
        return agent.llm.chat(
            messages=messages,
            tools=tools,
        )
    finally:
        stopped.set()
        reporter.join(timeout=0.1)
        elapsed = time.monotonic() - started
        print(
            "[LLM] Response received "
            f"after {elapsed:.1f}s."
        )


# =============================================================
# Main Agent Loop
# =============================================================


def run_agent_loop(
    agent,
    user_input: str,
) -> str:

    """
    Main orchestration loop.

    Responsibilities:

    - planning progress
    - context budget policy
    - token accounting
    - working summary updates
    - duplicate tool policy
    - validation orchestration
    - validation trend tracking
    - automatic rollback orchestration
    - completion gating
    - recovery
    - replanning
    - stopping decisions

    Tool execution mechanics belong to ToolExecutor /
    CheckpointingToolExecutor.

    Validation meaning belongs to ValidationPipeline.

    Rollback mechanics belong to RollbackEngine.

    Completion evidence belongs to CompletionGate.

    Final task completion additionally requires that an
    active implementation plan is complete.
    """

    messages = [
        {
            "role": "user",
            "content": user_input,
        }
    ]

    task_max_steps = int(
        getattr(agent, "task_max_steps", agent.max_steps)
    )

    # =========================================================
    # Main Step Budget
    # =========================================================

    for agent_step in range(
        task_max_steps
    ):

        print(
            f"\n[Agent Step "
            f"{agent_step + 1}/"
            f"{task_max_steps}]"
        )

        current_plan_step = None

        # =====================================================
        # Resolve Current Plan Step
        # =====================================================

        if agent.active_plan:

            current_plan_step = (
                agent.active_plan
                .start_current_step()
            )

            if current_plan_step:

                print(
                    f"\n[Current Plan Step] "
                    f"{current_plan_step.id}. "
                    f"{current_plan_step.description}"
                )

                print(
                    f"[Step Failures] "
                    f"{current_plan_step.attempts}/"
                    f"{agent.max_step_attempts}"
                )

                # =============================================
                # Step Attempt Budget Exceeded
                # =============================================

                if (
                    current_plan_step.attempts
                    >= agent.max_step_attempts
                ):

                    reason = (
                        f"Plan step "
                        f"{current_plan_step.id} "
                        "has exceeded its attempt budget. "
                        f"Current step: "
                        f"{current_plan_step.description}"
                    )

                    (
                        recovery_message,
                        should_continue,
                    ) = (
                        agent.recovery
                        .recover(
                            reason=reason,
                            replan_callback=(
                                agent.replan
                            ),
                        )
                    )

                    print(
                        "\n[Step Recovery]"
                    )

                    print(
                        recovery_message
                    )

                    if not should_continue:
                        record_task_outcome(agent, TaskOutcome.INCOMPLETE, reason)
                        return (
                            "Agent stopped because "
                            "the current plan step "
                            "could not be recovered."
                        )

                    current_plan_step.reset_attempts()

                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                recovery_message
                            ),
                        }
                    )

                    # Recovery may replace the plan.
                    if agent.active_plan:

                        current_plan_step = (
                            agent.active_plan
                            .start_current_step()
                        )

        # =====================================================
        # Remaining Agent Budget
        # =====================================================

        remaining_agent_steps = (
            task_max_steps
            - agent_step
        )

        action_controller = getattr(agent, "action_controller", None)
        if action_controller is not None and getattr(
            agent, "execution_policy", None
        ) is not None:
            action_controller.update_context(
                state=agent.task_progress_state(remaining_agent_steps),
                policy=agent.execution_policy,
                remaining_budget=remaining_agent_steps,
                acceptance_missing=(
                    not agent.validation_pipeline.state.acceptance_passed
                ),
            )

        finalization = getattr(agent, "finalization", None)
        if (
            finalization is not None
            and getattr(agent, "execution_policy", None) is not None
            and remaining_agent_steps < task_max_steps
            and finalization.enter_if_needed(
                remaining_agent_steps,
                agent.execution_policy,
            )
        ):
            print("\n[Finalization Mode]")
            if hasattr(agent, "task_state"):
                agent.task_state.mark_finalizing()
            if agent.active_plan is not None:
                reconciliation = agent.reconcile_plan_progress()
                if reconciliation["completed"]:
                    current_plan_step = agent.active_plan.start_current_step()
                    print(
                        "Final reconciliation completed steps: "
                        + ", ".join(
                            str(item["step_id"])
                            for item in reconciliation["completed"]
                        )
                    )

        # =====================================================
        # Context Budget Policy
        # =====================================================

        context_pressure = (
            agent.context_budget
            .pressure
        )

        print(
            "\n[Context Budget]"
        )

        print(
            "Last Prompt Tokens: "
            f"{agent.context_budget.last_prompt_tokens}"
        )

        print(
            "Usage: "
            f"{agent.context_budget.usage_ratio:.1%}"
        )

        print(
            "Pressure: "
            f"{context_pressure.value}"
        )

        turn = agent.turn_builder.build(
            agent,
            history=messages,
            user_input=user_input,
            current_plan_step=current_plan_step,
            remaining_agent_steps=remaining_agent_steps,
        )

        # =====================================================
        # LLM Call
        # =====================================================

        llm_response = _chat_with_heartbeat(
            agent,
            messages=turn.messages,
            tools=turn.tools,
        )

        # =====================================================
        # Token Metrics
        # =====================================================

        agent.token_metrics.record(
            llm_response.usage
        )

        execution_metrics = getattr(agent, "execution_metrics", None)
        if execution_metrics is not None:
            execution_metrics.observe_llm(
                call_count=agent.token_metrics.call_count,
                total_prompt_tokens=agent.token_metrics.total.prompt_tokens,
            )

        agent.context_budget.observe(
            llm_response
            .usage
            .prompt_tokens
        )

        print(
            "\n[Token Usage]"
        )

        print(
            "Prompt: "
            f"{llm_response.usage.prompt_tokens}"
        )

        print(
            "Completion: "
            f"{llm_response.usage.completion_tokens}"
        )

        print(
            "Total: "
            f"{llm_response.usage.total_tokens}"
        )

        print(
            "Task Total: "
            f"{agent.token_metrics.total.total_tokens}"
        )

        print(
            "Context Pressure: "
            f"{agent.context_budget.pressure.value}"
        )

        response = (
            llm_response.message
        )
        tool_calls = list(getattr(response, "tool_calls", None) or ())

        # =====================================================
        # LLM Returned Final Text
        # =====================================================

        if not tool_calls:
            content = getattr(response, "content", None) or ""
            remaining_budget = task_max_steps - agent_step - 1
            handling = agent.completion_handler.handle_text_response(
                agent,
                content=content,
                remaining_steps=remaining_budget,
            )
            if handling.finished:
                return handling.output or ""

            messages.append(
                {
                    "role": "assistant",
                    "content": content or "No tool action was taken.",
                }
            )
            if handling.followup_instruction:
                messages.append(
                    {
                        "role": "user",
                        "content": handling.followup_instruction,
                    }
                )
            continue

        # =====================================================
        # Preserve Assistant Tool Calls
        # =====================================================

        messages.append(
            response.model_dump(
                exclude_none=True
            )
        )

        restart_agent_loop = False

        early_stop = None

        # =====================================================
        # Execute Tool Calls
        # =====================================================

        for (
            tool_index,
            tool_call,
        ) in enumerate(
            tool_calls
        ):

            tool_name = (
                tool_call
                .function
                .name
            )

            call_run = agent.tool_batch_runner.run_call(agent, tool_call)
            arguments = call_run.arguments
            result = call_run.result

            # =================================================
            # Preparation Failed
            # =================================================

            if (
                call_run.preparation_failed
            ):

                agent.working_summary.record_tool_result(
                    tool_name=(
                        tool_name
                    ),
                    arguments={},
                    result=(
                        result
                    ),
                )

                if current_plan_step:

                    current_plan_step.increment_attempt()

                observation_text = (
                    result.to_llm_text()
                )

                print(
                    f"\n[Tool] "
                    f"{tool_name}"
                )

                print(
                    "\n[Tool Preparation Failed]"
                )

                print(
                    f"\n[Observation]\n"
                    f"{observation_text}"
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": (
                            tool_call.id
                        ),
                        "content": (
                            observation_text
                        ),
                    }
                )

                continue

            print(
                f"\n[Tool] "
                f"{tool_name}"
            )

            print(
                f"[Arguments] "
                f"{arguments}"
            )

            # =================================================
            # Deterministic Recovery Restriction
            # =================================================

            edit_retry = getattr(agent, "edit_retry", None)
            action_controller = getattr(agent, "action_controller", None)
            restriction = call_run.restriction

            if restriction is not None:
                if (
                    hasattr(agent, "task_state")
                    and restriction.failure_type == "action_required_restriction"
                ):
                    agent.task_state.require_action()
                metrics = getattr(agent, "execution_metrics", None)
                if metrics is not None and action_controller is not None:
                    metrics.action_required_trigger_count = (
                        action_controller.action_required_trigger_count
                    )
                if current_plan_step:
                    current_plan_step.increment_attempt()

                observation_text = result.to_llm_text()
                print("\n[Tool Restriction]")
                print(f"\n[Observation]\n{observation_text}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": observation_text,
                    }
                )
                commit_batch_transition(
                    messages,
                    tool_calls[tool_index + 1:],
                    reason="execution policy restricted the current tool batch",
                    followup=restriction.reason,
                )
                restart_agent_loop = True
                break

            # =================================================
            # 2. Duplicate Tool Policy
            # =================================================

            if call_run.duplicate_blocked:
                if current_plan_step:

                    current_plan_step.increment_attempt()

                print(
                    "\n[Duplicate Tool Blocked]"
                )

            else:
                if (
                    not result.success
                    and current_plan_step
                ):

                    current_plan_step.increment_attempt()

            # =================================================
            # 4. Working Summary
            # =================================================

            agent.working_summary.record_tool_result(
                tool_name=(
                    tool_name
                ),
                arguments=(
                    arguments
                ),
                result=(
                    result
                ),
            )

            # =================================================
            # 5. Tool Observation
            # =================================================

            observation_text = (
                result.to_llm_text()
            )

            print(
                f"\n[Observation]\n"
                f"{observation_text}"
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": (
                        tool_call.id
                    ),
                    "content": (
                        observation_text
                    ),
                }
            )

            # =================================================
            # 6. Record Action
            # =================================================

            execution_metrics = getattr(agent, "execution_metrics", None)
            if execution_metrics is not None:
                execution_metrics.record_tool(
                    tool_name,
                    llm_call_count=agent.token_metrics.call_count,
                    arguments=arguments,
                    success=result.success,
                )

            retry_message = None
            if edit_retry is not None:
                retry_message = edit_retry.observe(
                    tool_name,
                    arguments,
                    result,
                )
            if retry_message:
                stale_edit = str(result.data.get("failure_type", "")) == "stale_context"
                if hasattr(agent, "task_state"):
                    agent.task_state.transition_for_tool(
                        tool_name,
                        success=result.success,
                        stale_edit=stale_edit,
                    )
                if action_controller is not None:
                    action_controller.observe_action(
                        tool_name,
                        agent.task_progress_state(),
                    )
                close_tool_batch_before_control_transition(
                    messages,
                    tool_calls[tool_index + 1:],
                    "bounded stale-edit recovery changed the next allowed action",
                    followup_user_message=retry_message,
                )
                restart_agent_loop = True
                break

            is_validation_action = (
                tool_name in {"run_tests", "validate_static_web"}
                or (
                    tool_name == "run_command"
                    and str(arguments.get("purpose", "diagnostic")).strip().lower()
                    == "acceptance"
                )
            )
            if (
                hasattr(agent, "task_state")
                and not is_validation_action
                and not (tool_name in EDIT_TOOL_NAMES and result.success)
            ):
                agent.task_state.transition_for_tool(
                    tool_name,
                    success=result.success,
                )

            if (
                tool_name not in EDIT_TOOL_NAMES
                and hasattr(agent, "step_evidence")
            ):
                agent.step_evidence.record(
                    step_id=(
                        current_plan_step.id
                        if current_plan_step
                        else None
                    ),
                    edit_revision=(
                        agent.validation_pipeline.state.edit_revision
                    ),
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                )

            # =================================================
            # Successful Edit
            #
            # CheckpointingToolExecutor already performed:
            #
            # capture
            # ↓
            # edit
            # ↓
            # seal
            #
            # Loop now creates the logical revision.
            # =================================================

            if (
                tool_name
                in EDIT_TOOL_NAMES
                and result.success
            ):

                revision = (
                    agent.validation_pipeline
                    .record_edit()
                )

                if hasattr(agent, "task_state"):
                    agent.task_state.transition_for_tool(
                        tool_name,
                        success=True,
                    )

                print(
                    "\n[Edit Applied]"
                )

                if hasattr(agent, "step_evidence"):
                    agent.step_evidence.record(
                        step_id=(
                            current_plan_step.id
                            if current_plan_step
                            else None
                        ),
                        edit_revision=revision,
                        tool_name=tool_name,
                        arguments=arguments,
                        result=result,
                    )

                agent.progress.mark_meaningful_progress()

                if action_controller is not None:
                    action_controller.observe_action(
                        tool_name,
                        agent.task_progress_state(),
                    )

                print(
                    "[Validation Revision] "
                    f"{revision}"
                )

                checkpoint_id = (
                    result.data.get(
                        "checkpoint_id"
                    )
                )

                if checkpoint_id:

                    print(
                        "[Checkpoint] "
                        f"{checkpoint_id}"
                    )

                reconciliation = (
                    agent.reconcile_plan_progress()
                )
                reconciled_steps = reconciliation[
                    "completed"
                ]

                if reconciled_steps:
                    print("\n[Plan Reconciliation]")
                    print(
                        "Machine criteria completed steps: "
                        + ", ".join(
                            str(item["step_id"])
                            for item in reconciled_steps
                        )
                    )
                    close_tool_batch_before_control_transition(
                        messages,
                        tool_calls[
                            tool_index + 1:
                        ],
                        (
                            "machine-checkable plan criteria "
                            "advanced the active plan"
                        ),
                    )
                    restart_agent_loop = True
                    break

            if (
                action_controller is not None
                and (
                    tool_name not in EDIT_TOOL_NAMES
                    or not result.success
                )
            ):
                action_controller.observe_action(
                    tool_name,
                    agent.task_progress_state(),
                )

            # =================================================
            # Complete Plan Step
            # =================================================

            if (
                tool_name
                == "complete_plan_step"
            ):

                completed = bool(
                    result.data.get(
                        "completed",
                        False,
                    )
                )

                if completed:

                    close_tool_batch_before_control_transition(
                        messages,
                        tool_calls[
                            tool_index + 1:
                        ],
                        (
                            "the active plan step "
                            "was completed and "
                            "remaining calls were "
                            "generated from stale "
                            "plan context"
                        ),
                    )

                    restart_agent_loop = True

                    break

                continue

            # =================================================
            # Replan
            # =================================================

            if (
                tool_name
                == "replan"
            ):

                replanned = bool(
                    result.data.get(
                        "replanned",
                        False,
                    )
                )

                if replanned:

                    close_tool_batch_before_control_transition(
                        messages,
                        tool_calls[
                            tool_index + 1:
                        ],
                        (
                            "the implementation "
                            "plan was revised and "
                            "remaining calls were "
                            "generated from the "
                            "previous plan"
                        ),
                    )

                    restart_agent_loop = True

                    break

                continue

            # =================================================
            # Structured Validation
            # =================================================

            if (
                tool_name == "run_tests"
                or tool_name == "validate_static_web"
                or (
                    tool_name == "run_command"
                    and str(
                        arguments.get(
                            "purpose",
                            "diagnostic",
                        )
                    ).strip().lower()
                    == "acceptance"
                )
            ):

                evidence = (
                    agent.validation_pipeline
                    .observe(
                        tool_name=(
                            tool_name
                        ),
                        arguments=(
                            arguments
                        ),
                        result=(
                            result
                        ),
                    )
                )

                if (
                    evidence
                    is not None
                ):

                    if hasattr(agent, "task_state"):
                        agent.task_progress_state()
                        agent.task_state.transition_for_tool(
                            tool_name,
                            success=result.success,
                            validation_outcome=evidence.outcome,
                        )

                    reconciliation = (
                        agent.reconcile_plan_progress()
                    )
                    reconciled_steps = reconciliation[
                        "completed"
                    ]

                    print(
                        "\n[Validation Evidence]"
                    )

                    print(
                        "Revision: "
                        f"{evidence.edit_revision}"
                    )

                    print(
                        "Scope: "
                        f"{evidence.scope.value}"
                    )

                    print(
                        "Purpose: "
                        f"{evidence.purpose.value}"
                    )

                    print(
                        "Outcome: "
                        f"{evidence.outcome.value}"
                    )

                    control_decision = (
                        agent.validation_orchestrator.apply(
                            agent=agent,
                            evidence=evidence,
                        )
                    )

                    if action_controller is not None:
                        action_controller.observe_action(
                            tool_name,
                            agent.task_progress_state(),
                            getattr(agent, "latest_progress_signal", None),
                        )

                    early_stop = control_decision.early_stop
                    restart_agent_loop = control_decision.restart

                    if reconciled_steps:
                        print("\n[Plan Reconciliation]")
                        print(
                            "Validation-backed criteria completed "
                            "steps: "
                            + ", ".join(
                                str(item["step_id"])
                                for item in reconciled_steps
                            )
                        )
                        restart_agent_loop = True

                    if (
                        early_stop
                        or restart_agent_loop
                    ):
                        close_tool_batch_before_control_transition(
                            messages,
                            tool_calls[
                                tool_index + 1:
                            ],
                            control_decision.skipped_reason
                            or (
                                "validation changed agent loop "
                                "control flow"
                            ),
                            followup_user_message=(
                                control_decision.followup_message
                            ),
                        )

                        break

        # =====================================================
        # After Tool Batch
        # =====================================================

        if early_stop:
            metrics = getattr(agent, "execution_metrics", None)
            if metrics is None or metrics.final_outcome is None:
                outcome = (
                    TaskOutcome.BLOCKED
                    if "block" in early_stop.casefold()
                    else TaskOutcome.INCOMPLETE
                )
                record_task_outcome(agent, outcome, early_stop)
                return agent.completion_handler.build_task_report(
                    agent,
                    outcome=outcome,
                    reason=early_stop,
                )
            return early_stop

        if restart_agent_loop:

            continue

        # =====================================================
        # Completion Gate After Tool Batch
        #
        # Validation READY alone is not enough.
        # An active plan must also be complete.
        # =====================================================

        handling = agent.completion_handler.check_after_batch(agent)
        if handling.finished:
            return handling.output or ""

        action_controller = getattr(agent, "action_controller", None)
        policy = getattr(agent, "execution_policy", None)
        if (
            action_controller is not None
            and policy is not None
            and action_controller.update_pressure(policy)
        ):
            if hasattr(agent, "task_state"):
                agent.task_state.require_action()
            metrics = getattr(agent, "execution_metrics", None)
            if metrics is not None:
                metrics.action_required_trigger_count = (
                    action_controller.action_required_trigger_count
                )
            print("\n[ACTION_REQUIRED]")
            print(action_controller.INSTRUCTION)
            messages.append(
                {"role": "user", "content": action_controller.INSTRUCTION}
            )

    # =========================================================
    # Agent Budget Exhausted
    # =========================================================

    if getattr(agent, "active_plan", None) is not None:
        reconciliation = agent.reconcile_plan_progress()
        if reconciliation["completed"]:
            print("\n[Final Reconciliation]")
            print(
                "Completed steps before budget stop: "
                + ", ".join(
                    str(item["step_id"])
                    for item in reconciliation["completed"]
                )
            )

    exhausted = agent.completion_handler.handle_budget_exhausted(
        agent,
        reason="The maximum number of agent steps was reached.",
    )
    return exhausted.output or "Task incomplete."


# Compatibility re-exports. Validation policy is owned by the focused
# orchestration component; existing integrations may continue importing these
# names from agent.loop during the migration window.
from .validation_orchestrator import (  # noqa: E402
    acceptance_evidence_reminder,
    active_plan_incomplete,
    apply_validation_evidence,
    can_complete_edit_task,
    can_finish_edit_task,
    completion_result,
    evaluate_completion,
    rollback_regressed_edit,
    validation_evidence_key,
)
