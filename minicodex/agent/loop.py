"""Agent execution loop."""

from .context import (
    compact_messages_for_pressure,
)
from .state import StepStatus
from .validation import (
    ValidationEvidence,
    ValidationNextAction,
    ValidationOutcome,
)

from ..tools.results import ToolResult


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


# =============================================================
# Main Agent Loop
# =============================================================


def run_agent_loop(
    agent,
    user_input: str,
) -> str:

    """
    Main orchestration loop.

    The loop owns Agent-level orchestration:
    - planning progress
    - context budget policy
    - token accounting
    - working summary updates
    - duplicate policy
    - validation orchestration
    - recovery
    - plan transitions
    - stopping decisions

    Tool execution mechanics are delegated to ToolExecutor.

    Validation meaning and edit-revision truth are delegated
    to ValidationPipeline.
    """

    messages = [
        {
            "role": "user",
            "content": user_input,
        }
    ]

    # =========================================================
    # Main Step Budget
    # =========================================================

    for agent_step in range(
        agent.max_steps
    ):

        print(
            f"\n[Agent Step "
            f"{agent_step + 1}/"
            f"{agent.max_steps}]"
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
                # Step Failure Budget Exceeded
                # =============================================

                if (
                    current_plan_step.attempts
                    >= agent.max_step_attempts
                ):

                    reason = (
                        f"Plan step "
                        f"{current_plan_step.id} "
                        f"has exceeded its attempt budget. "
                        f"Current step: "
                        f"{current_plan_step.description}"
                    )

                    (
                        recovery_message,
                        should_continue,
                    ) = (
                        agent.recovery.recover(
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

                    if agent.active_plan:

                        current_plan_step = (
                            agent.active_plan
                            .start_current_step()
                        )

        # =====================================================
        # Remaining Agent Budget
        # =====================================================

        remaining_agent_steps = (
            agent.max_steps
            - agent_step
        )

        # =====================================================
        # Context Budget Policy
        # =====================================================

        context_pressure = (
            agent.context_budget.pressure
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

        compact_messages_for_pressure(
            messages,
            context_pressure,
        )

        # =====================================================
        # Build System Prompt
        # =====================================================

        system_prompt = (
            agent._build_system_prompt(
                user_input=user_input,
                plan=agent.active_plan,
                current_step=(
                    current_plan_step
                ),
                remaining_agent_steps=(
                    remaining_agent_steps
                ),
            )
        )

        llm_messages = [
            {
                "role": "system",
                "content": (
                    system_prompt
                ),
            }
        ] + messages

        # =====================================================
        # Dynamic Turn Context
        # =====================================================

        build_turn = getattr(
            agent,
            "_build_turn_context",
            None,
        )

        if callable(
            build_turn
        ):

            llm_messages.append(
                {
                    "role": "user",
                    "content": build_turn(
                        plan=(
                            agent.active_plan
                        ),
                        current_step=(
                            current_plan_step
                        ),
                        remaining_agent_steps=(
                            remaining_agent_steps
                        ),
                    ),
                }
            )

        # =====================================================
        # LLM Call
        # =====================================================

        llm_response = (
            agent.llm.chat(
                messages=(
                    llm_messages
                ),
                tools=(
                    agent.registry
                    .get_schemas()
                ),
            )
        )

        # =====================================================
        # Token Metrics
        # =====================================================

        agent.token_metrics.record(
            llm_response.usage
        )

        # =====================================================
        # Context Observation
        # =====================================================

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

        # =====================================================
        # Extract Provider Message
        # =====================================================

        response = (
            llm_response.message
        )

        # =====================================================
        # LLM Returned Final Text
        # =====================================================

        if not response.tool_calls:

            content = (
                response.content
                or ""
            )

            # =============================================
            # Validated Edit May Finish Task
            # =============================================

            if has_validated_edit(
                agent
            ):

                return (
                    content
                    or summarize_agent_stop(
                        agent,
                        (
                            "Task validated: "
                            "the current edit revision "
                            "passed full validation."
                        ),
                    )
                )

            # =============================================
            # Prevent Premature Finish
            # =============================================

            if (
                agent.active_plan
                and not (
                    agent.active_plan
                    .is_completed()
                )
            ):

                print(
                    "\n[Warning] "
                    "LLM returned final answer "
                    "before all plan steps "
                    "were completed."
                )

                remaining_budget = (
                    agent.max_steps
                    - agent_step
                    - 1
                )

                if remaining_budget > 0:

                    messages.append(
                        {
                            "role": "assistant",
                            "content": (
                                content
                                or (
                                    "Stopped before "
                                    "the plan was complete."
                                )
                            ),
                        }
                    )

                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                INCOMPLETE_PLAN_REMINDER
                            ),
                        }
                    )

                    continue

                return summarize_agent_stop(
                    agent,
                    (
                        "Agent stopped with "
                        "unfinished plan steps."
                    ),
                    content,
                )

            return content

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
            response.tool_calls
        ):

            tool_name = (
                tool_call.function.name
            )

            # =================================================
            # 1. Prepare Tool Call
            # =================================================

            prepared = (
                agent.tool_executor
                .prepare(
                    tool_name=(
                        tool_name
                    ),
                    raw_arguments=(
                        tool_call
                        .function
                        .arguments
                    ),
                )
            )

            # =================================================
            # Preparation Failure
            # =================================================

            if (
                prepared.error
                is not None
            ):

                result = (
                    prepared.error
                )

                agent.working_summary.record_tool_result(
                    tool_name=tool_name,
                    arguments={},
                    result=result,
                )

                if current_plan_step:

                    (
                        current_plan_step
                        .increment_attempt()
                    )

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

            arguments = (
                prepared.arguments
            )

            print(
                f"\n[Tool] "
                f"{tool_name}"
            )

            print(
                f"[Arguments] "
                f"{arguments}"
            )

            # =================================================
            # 2. Duplicate Policy
            # =================================================

            (
                allowed,
                duplicate_reason,
            ) = (
                agent.progress
                .check_duplicate_tool_call(
                    tool_name,
                    arguments,
                )
            )

            if not allowed:

                result = ToolResult(
                    success=False,
                    summary=(
                        f"Tool call "
                        f"'{tool_name}' "
                        "was blocked as "
                        "a duplicate."
                    ),
                    data={
                        "tool_name": (
                            tool_name
                        ),
                        "failure_type": (
                            "duplicate_call"
                        ),
                    },
                    error=(
                        duplicate_reason
                    ),
                )

                if current_plan_step:

                    (
                        current_plan_step
                        .increment_attempt()
                    )

                print(
                    "\n[Duplicate Tool Blocked]"
                )

            else:

                # =============================================
                # 3. Reliable Execution
                # =============================================

                execution = (
                    agent.tool_executor
                    .execute_prepared(
                        prepared
                    )
                )

                result = (
                    execution.result
                )

                if (
                    not result.success
                    and current_plan_step
                ):

                    (
                        current_plan_step
                        .increment_attempt()
                    )

            # =================================================
            # 4. Working Summary
            # =================================================

            agent.working_summary.record_tool_result(
                tool_name=tool_name,
                arguments=arguments,
                result=result,
            )

            # =================================================
            # 5. ToolResult → LLM Observation
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
            # 6. Record Agent Action
            # =================================================

            agent.progress.record_action(
                tool_name
            )

            # =================================================
            # Successful Edit
            #
            # Every successful edit creates a NEW revision.
            # All previous validation evidence becomes stale.
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

                print(
                    "\n[Edit Applied]"
                )

                print(
                    "[Validation Revision] "
                    f"{revision}"
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

                    append_skipped_tool_results(
                        messages,
                        response.tool_calls[
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

                    append_skipped_tool_results(
                        messages,
                        response.tool_calls[
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
            # Structured Validation Pipeline
            # =================================================

            if (
                tool_name
                == "run_tests"
            ):

                evidence = (
                    agent.validation_pipeline
                    .observe(
                        tool_name=tool_name,
                        arguments=arguments,
                        result=result,
                    )
                )

                if (
                    evidence
                    is not None
                ):

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
                        "Outcome: "
                        f"{evidence.outcome.value}"
                    )

                    (
                        early_stop,
                        restart_agent_loop,
                    ) = (
                        apply_validation_evidence(
                            agent=agent,
                            evidence=evidence,
                            messages=messages,
                        )
                    )

                    if (
                        early_stop
                        or restart_agent_loop
                    ):

                        append_skipped_tool_results(
                            messages,
                            response.tool_calls[
                                tool_index + 1:
                            ],
                            (
                                "validation changed "
                                "agent loop control flow"
                            ),
                        )

                        break

            # =================================================
            # General Action Stall Detection
            # =================================================

            if (
                agent._step_likely_requires_edit(
                    current_plan_step
                )
                and (
                    agent.progress
                    .is_action_stalled()
                )
            ):

                reason = (
                    "The agent has repeatedly "
                    "inspected or validated code "
                    "without making a meaningful edit."
                )

                (
                    recovery_message,
                    should_continue,
                ) = (
                    agent.recovery.recover(
                        reason=reason,
                        replan_callback=(
                            agent.replan
                        ),
                    )
                )

                print(
                    "\n[Progress Recovery]"
                )

                print(
                    recovery_message
                )

                if not should_continue:

                    append_skipped_tool_results(
                        messages,
                        response.tool_calls[
                            tool_index + 1:
                        ],
                        (
                            "progress recovery "
                            "stopped execution"
                        ),
                    )

                    return (
                        "Agent stopped because "
                        "meaningful progress "
                        "could not be made."
                    )

                messages.append(
                    {
                        "role": "user",
                        "content": (
                            recovery_message
                        ),
                    }
                )

                restart_agent_loop = True

                append_skipped_tool_results(
                    messages,
                    response.tool_calls[
                        tool_index + 1:
                    ],
                    (
                        "progress recovery "
                        "restarted the loop"
                    ),
                )

                break

        # =====================================================
        # After Tool Call Batch
        # =====================================================

        if early_stop:

            return early_stop

        if restart_agent_loop:

            continue

        # =====================================================
        # Stop When Current Edit Revision Is Fully Validated
        # =====================================================

        if has_validated_edit(
            agent
        ):

            return summarize_agent_stop(
                agent,
                (
                    "Task validated: "
                    "the full test suite "
                    "passed for the current "
                    "edit revision."
                ),
            )

    # =========================================================
    # Agent Budget Exhausted
    # =========================================================

    return summarize_agent_stop(
        agent,
        (
            "Agent stopped because "
            "the maximum number of "
            "agent steps was reached."
        ),
    )


# =============================================================
# Current Edit Validation
# =============================================================


def has_validated_edit(
    agent,
) -> bool:

    pipeline = getattr(
        agent,
        "validation_pipeline",
        None,
    )

    if (
        pipeline
        is None
    ):

        return False

    return (
        pipeline
        .current_edit_validated()
    )


# =============================================================
# Validation Policy Orchestration
# =============================================================


def apply_validation_evidence(
    agent,
    evidence: ValidationEvidence,
    messages: list,
) -> tuple[
    str | None,
    bool,
]:

    """
    Convert normalized ValidationEvidence into AgentLoop
    orchestration.

    Responsibilities intentionally remain separated:

    ValidationPipeline:
        What does the evidence mean?

    ProgressController:
        Is repeated failure improving or stalled?

    AgentLoop:
        What should execution do next?
    """

    # =========================================================
    # Evidence → Failure Count For Progress Trend
    # =========================================================

    if (
        evidence.outcome
        == ValidationOutcome.PASSED
    ):

        failed_count = 0

    elif (
        evidence.outcome
        == ValidationOutcome.FAILED
    ):

        failed_count = (
            evidence.failed_count
        )

    else:

        failed_count = None

    validation_progress = (
        agent.progress
        .track_validation(
            failed_count
        )
    )

    if (
        validation_progress.message
    ):

        print(
            "\n[Validation Progress]"
        )

        print(
            validation_progress.message
        )

    if (
        validation_progress
        .meaningful_progress
    ):

        agent.recovery.mark_progress()

        print(
            "\n[Meaningful Progress Detected]"
        )

    # =========================================================
    # ValidationPipeline Policy Decision
    # =========================================================

    next_action = (
        agent.validation_pipeline
        .next_action(
            evidence
        )
    )

    print(
        "\n[Validation Policy]"
    )

    print(
        "Next action: "
        f"{next_action.value}"
    )

    # =========================================================
    # Current Revision Fully Validated
    # =========================================================

    if (
        next_action
        == (
            ValidationNextAction
            .TASK_VALIDATED
        )
    ):

        return (
            None,
            False,
        )

    # =========================================================
    # Targeted PASS → Escalate To Full Suite
    # =========================================================

    if (
        next_action
        == (
            ValidationNextAction
            .RUN_FULL_VALIDATION
        )
    ):

        messages.append(
            {
                "role": "user",
                "content": (
                    "Targeted validation passed for "
                    "the current edit revision, but "
                    "full validation is still required. "
                    "Run the full test suite with "
                    "run_tests(path='.') before "
                    "claiming task completion."
                ),
            }
        )

        return (
            None,
            True,
        )

    # =========================================================
    # Inconclusive Validation
    # =========================================================

    if (
        next_action
        == (
            ValidationNextAction
            .INVESTIGATE_INCONCLUSIVE
        )
    ):

        messages.append(
            {
                "role": "user",
                "content": (
                    "Validation was inconclusive. "
                    "Do not treat it as either a code "
                    "failure or successful validation. "
                    "Inspect why validation could not "
                    "produce reliable evidence and obtain "
                    "new evidence."
                ),
            }
        )

        return (
            None,
            True,
        )

    # =========================================================
    # Failed But Not Yet Stalled
    # =========================================================

    if (
        next_action
        == (
            ValidationNextAction
            .FIX_FAILURE
        )
        and not (
            validation_progress
            .stalled
        )
    ):

        return (
            None,
            False,
        )

    # =========================================================
    # No Stall
    # =========================================================

    if not (
        validation_progress
        .stalled
    ):

        return (
            None,
            False,
        )

    # =========================================================
    # Validation Recovery
    # =========================================================

    reason = (
        "Validation is repeatedly failing "
        "without meaningful improvement. "
        f"{validation_progress.message}"
    )

    (
        recovery_message,
        should_continue,
    ) = (
        agent.recovery.recover(
            reason=reason,
            replan_callback=(
                agent.replan
            ),
        )
    )

    print(
        "\n[Validation Recovery]"
    )

    print(
        recovery_message
    )

    if not should_continue:

        return (
            (
                "Agent stopped because "
                "validation remained stalled."
            ),
            False,
        )

    messages.append(
        {
            "role": "user",
            "content": (
                recovery_message
            ),
        }
    )

    return (
        None,
        True,
    )


# =============================================================
# Tool Call History Integrity
# =============================================================


def append_skipped_tool_results(
    messages: list,
    tool_calls,
    reason: str,
) -> None:

    """
    Tool-call protocols expect every assistant tool call
    to receive a corresponding tool response.

    When plan/recovery/validation state changes midway
    through a batch, remaining calls are deliberately
    skipped instead of executed.
    """

    for tool_call in tool_calls:

        messages.append(
            {
                "role": "tool",
                "tool_call_id": (
                    tool_call.id
                ),
                "content": (
                    "Tool call skipped because "
                    f"{reason}."
                ),
            }
        )


# =============================================================
# Agent Stop Summary
# =============================================================


def summarize_agent_stop(
    agent,
    reason: str,
    last_text: str = "",
) -> str:

    lines = [
        reason
    ]

    plan = getattr(
        agent,
        "active_plan",
        None,
    )

    # =========================================================
    # Plan Status
    # =========================================================

    if plan:

        completed = [
            step
            for step
            in plan.all_steps()
            if (
                step.status
                == StepStatus.COMPLETED
            )
        ]

        remaining = [
            step
            for step
            in plan.all_steps()
            if step.status in {
                StepStatus.PENDING,
                StepStatus.IN_PROGRESS,
            }
        ]

        lines.append(
            (
                f"Plan progress: "
                f"{len(completed)} completed, "
                f"{len(remaining)} remaining."
            )
        )

        if remaining:

            lines.append(
                (
                    "Next unfinished step: "
                    f"{remaining[0].id}. "
                    f"{remaining[0].description}"
                )
            )

        if plan.is_completed():

            lines.append(
                "All plan steps are "
                "marked complete."
            )

    # =========================================================
    # Validation State
    # =========================================================

    pipeline = getattr(
        agent,
        "validation_pipeline",
        None,
    )

    if (
        pipeline is not None
    ):

        state = (
            pipeline.state
        )

        evidence = (
            state.latest_evidence
        )

        lines.append(
            (
                "Validation revision: "
                f"{state.edit_revision}."
            )
        )

        if evidence is not None:

            lines.append(
                (
                    "Last validation: "
                    f"scope={evidence.scope.value}, "
                    f"outcome={evidence.outcome.value}, "
                    f"revision="
                    f"{evidence.edit_revision}."
                )
            )

        if (
            pipeline
            .current_edit_validated()
        ):

            lines.append(
                "Current edit revision has "
                "full validation evidence."
            )

    # =========================================================
    # Validation Failure Trend
    # =========================================================

    failed = getattr(
        agent.progress,
        "last_validation_failed_count",
        None,
    )

    if failed == 0:

        lines.append(
            "Latest validation failure count: 0."
        )

    elif failed is not None:

        lines.append(
            (
                "Latest validation failure count: "
                f"{failed}."
            )
        )

    # =========================================================
    # Token Metrics
    # =========================================================

    token_metrics = getattr(
        agent,
        "token_metrics",
        None,
    )

    if (
        token_metrics
        is not None
    ):

        lines.append(
            (
                "LLM usage: "
                f"{token_metrics.call_count} calls, "
                f"{token_metrics.total.prompt_tokens} "
                "prompt tokens, "
                f"{token_metrics.total.completion_tokens} "
                "completion tokens, "
                f"{token_metrics.total.total_tokens} "
                "total tokens."
            )
        )

    # =========================================================
    # Context Budget
    # =========================================================

    context_budget = getattr(
        agent,
        "context_budget",
        None,
    )

    if (
        context_budget
        is not None
    ):

        lines.append(
            (
                "Context state: "
                f"{context_budget.last_prompt_tokens} "
                "prompt tokens in the last call, "
                f"{context_budget.usage_ratio:.1%} "
                "of configured budget, "
                f"pressure="
                f"{context_budget.pressure.value}."
            )
        )

    # =========================================================
    # Working Summary
    # =========================================================

    working_summary = getattr(
        agent,
        "working_summary",
        None,
    )

    if (
        working_summary is not None
        and working_summary.items
    ):

        lines.append(
            "Working summary:"
        )

        lines.append(
            working_summary.render()
        )

    # =========================================================
    # Last LLM Text
    # =========================================================

    if last_text:

        lines.append(
            last_text
        )

    return "\n".join(
        lines
    )