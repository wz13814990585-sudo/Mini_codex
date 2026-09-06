"""Agent execution loop."""

from .completion import (
    CompletionGate,
    CompletionStatus,
)
from .context import (
    compact_messages_for_pressure,
)
from .progress import (
    ValidationStatus,
)
from .state import (
    StepStatus,
)
from .validation import (
    ValidationEvidence,
    ValidationNextAction,
    ValidationOutcome,
)

from ..tools.results import (
    ToolResult,
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


COMPLETION_GATE = (
    CompletionGate()
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

    Completion truth belongs to CompletionGate.
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

                    # Recovery may replace the active plan.
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

        compact_messages_for_pressure(
            messages,
            context_pressure,
        )

        # =====================================================
        # Build System Prompt
        # =====================================================

        system_prompt = (
            agent._build_system_prompt(
                user_input=(
                    user_input
                ),
                plan=(
                    agent.active_plan
                ),
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
                    "content": (
                        build_turn(
                            plan=(
                                agent.active_plan
                            ),
                            current_step=(
                                current_plan_step
                            ),
                            remaining_agent_steps=(
                                remaining_agent_steps
                            ),
                        )
                    ),
                }
            )

        # =====================================================
        # LLM Call
        # =====================================================

        llm_response = (
            agent.llm
            .chat(
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
        # Provider Message
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

            completion = (
                evaluate_completion(
                    agent
                )
            )

            print(
                "\n[Completion Gate]"
            )

            print(
                "Status: "
                f"{completion.status.value}"
            )

            print(
                "Reason: "
                f"{completion.reason}"
            )

            # =============================================
            # Editing Task Fully Validated
            # =============================================

            if (
                completion.can_complete
            ):

                return (
                    content
                    or summarize_agent_stop(
                        agent,
                        (
                            "Task completed with "
                            "acceptance evidence and "
                            "full regression evidence."
                        ),
                    )
                )

            # =============================================
            # There Has Been An Edit
            #
            # Once a mutation occurred, completion evidence
            # cannot be bypassed by final LLM prose.
            # =============================================

            if (
                completion.has_edit
                and not completion.can_complete
            ):

                remaining_budget = (
                    agent.max_steps
                    - agent_step
                    - 1
                )

                if (
                    remaining_budget
                    > 0
                ):

                    messages.append(
                        {
                            "role": "assistant",
                            "content": (
                                content
                                or (
                                    "The implementation "
                                    "appears complete."
                                )
                            ),
                        }
                    )

                    # =====================================
                    # Acceptance Missing
                    # =====================================

                    if (
                        completion.status
                        == (
                            CompletionStatus
                            .NEEDS_ACCEPTANCE
                        )
                    ):

                        reminder = (
                            "The current edit revision "
                            "cannot complete yet because "
                            "acceptance evidence is missing. "
                            "Run a specific relevant test "
                            "that demonstrates the user's "
                            "requested behavior using "
                            "run_tests("
                            "path=<specific_test>, "
                            "purpose='acceptance')."
                        )

                    # =====================================
                    # Full Regression Missing
                    # =====================================

                    elif (
                        completion.status
                        == (
                            CompletionStatus
                            .NEEDS_FULL_VALIDATION
                        )
                    ):

                        reminder = (
                            "Acceptance evidence exists, "
                            "but full regression validation "
                            "is still missing. Run "
                            "run_tests("
                            "path='.', "
                            "purpose='regression')."
                        )

                    else:

                        reminder = (
                            "The task does not yet have "
                            "sufficient completion evidence."
                        )

                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                reminder
                            ),
                        }
                    )

                    continue

                return summarize_agent_stop(
                    agent,
                    (
                        "Agent stopped before "
                        "completion evidence was "
                        "fully established. "
                        f"{completion.reason}"
                    ),
                    content,
                )

            # =============================================
            # Incomplete Plan Protection
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

                if (
                    remaining_budget
                    > 0
                ):

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

            # =============================================
            # Read-Only / Informational Task
            # =============================================

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
                tool_call
                .function
                .name
            )

            # =================================================
            # 1. Prepare
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
            # Preparation Failed
            # =================================================

            if (
                prepared.error
                is not None
            ):

                result = (
                    prepared.error
                )

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

                result = (
                    ToolResult(
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
                )

                if current_plan_step:

                    current_plan_step.increment_attempt()

                print(
                    "\n[Duplicate Tool Blocked]"
                )

            else:

                # =============================================
                # 3. Reliable Tool Execution
                #
                # At Stage 10 this may actually be
                # CheckpointingToolExecutor.
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

            agent.progress.record_action(
                tool_name
            )

            # =================================================
            # Successful Edit
            #
            # CheckpointingToolExecutor has already:
            #
            # capture → edit → seal
            #
            # Here Loop creates the logical workspace revision.
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
            # Structured Validation
            # =================================================

            if (
                tool_name
                == "run_tests"
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

                    (
                        early_stop,
                        restart_agent_loop,
                    ) = (
                        apply_validation_evidence(
                            agent=(
                                agent
                            ),
                            evidence=(
                                evidence
                            ),
                            messages=(
                                messages
                            ),
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
                    agent.recovery
                    .recover(
                        reason=(
                            reason
                        ),
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
        # After Tool Batch
        # =====================================================

        if early_stop:

            return early_stop

        if restart_agent_loop:

            continue

        # =====================================================
        # Completion Gate After Tool Batch
        # =====================================================

        completion = (
            evaluate_completion(
                agent
            )
        )

        if (
            completion.can_complete
        ):

            return summarize_agent_stop(
                agent,
                (
                    "Task completed: "
                    "the current edit revision "
                    "has acceptance evidence "
                    "and full regression evidence."
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
# Validation Evidence Identity
# =============================================================


def validation_evidence_key(
    evidence: ValidationEvidence,
) -> str:

    """
    Identity of one comparable validation series.

    Failure counts may only be compared when purpose,
    scope and test path are identical.

    Example:

        acceptance|targeted|tests/test_divide.py

    must never be compared with:

        regression|full|.
    """

    return (
        f"{evidence.purpose.value}"
        f"|{evidence.scope.value}"
        f"|{evidence.path or ''}"
    )


# =============================================================
# Completion Gate
# =============================================================


def evaluate_completion(
    agent,
):

    pipeline = getattr(
        agent,
        "validation_pipeline",
        None,
    )

    if (
        pipeline
        is None
    ):

        return (
            COMPLETION_GATE
            .evaluate(
                edit_revision=0,
                has_edit=False,
                acceptance_passed=False,
                full_validation_passed=False,
            )
        )

    state = (
        pipeline.state
    )

    return (
        COMPLETION_GATE
        .evaluate(
            edit_revision=(
                state.edit_revision
            ),
            has_edit=(
                state.has_edit
            ),
            acceptance_passed=(
                state.acceptance_passed
            ),
            full_validation_passed=(
                state.full_passed
            ),
        )
    )


def can_complete_edit_task(
    agent,
) -> bool:

    return (
        evaluate_completion(
            agent
        )
        .can_complete
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
    Convert normalized ValidationEvidence into orchestration.

    ValidationPipeline:
        What does the validation mean?

    ProgressController:
        Is the same validation target improving or regressing?

    RollbackEngine:
        Restore the before-state when policy chooses rollback.

    CompletionGate:
        Is there enough evidence to finish?

    AgentLoop:
        What happens next?
    """

    # =========================================================
    # Evidence → Failed Count
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

    # =========================================================
    # Comparable Validation Trend
    # =========================================================

    validation_progress = (
        agent.progress
        .track_validation(
            failed_count,
            validation_key=(
                validation_evidence_key(
                    evidence
                )
            ),
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

    # =========================================================
    # Automatic Rollback On Strict Regression
    #
    # Only FAILED evidence can trigger this.
    #
    # PASSED → another suite with failures is protected
    # by validation_key and therefore starts a new series.
    # =========================================================

    if (
        evidence.outcome
        == ValidationOutcome.FAILED
        and (
            validation_progress.status
            == ValidationStatus.REGRESSED
        )
    ):

        rollback_control = (
            rollback_regressed_edit(
                agent=(
                    agent
                ),
                evidence=(
                    evidence
                ),
                validation_progress=(
                    validation_progress
                ),
                messages=(
                    messages
                ),
            )
        )

        if (
            rollback_control
            is not None
        ):

            return rollback_control

    # =========================================================
    # Meaningful Progress
    # =========================================================

    if (
        validation_progress
        .meaningful_progress
    ):

        agent.recovery.mark_progress()

        print(
            "\n[Meaningful Progress Detected]"
        )

    # =========================================================
    # Validation Pipeline Decision
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
    # Both Acceptance + Full Regression
    # =========================================================

    if (
        next_action
        == (
            ValidationNextAction
            .TASK_VALIDATED
        )
    ):

        completion = (
            evaluate_completion(
                agent
            )
        )

        print(
            "\n[Completion Gate]"
        )

        print(
            "Status: "
            f"{completion.status.value}"
        )

        return (
            None,
            False,
        )

    # =========================================================
    # Need Acceptance
    # =========================================================

    if (
        next_action
        == (
            ValidationNextAction
            .RUN_ACCEPTANCE_VALIDATION
        )
    ):

        messages.append(
            {
                "role": "user",
                "content": (
                    "Regression validation is not enough "
                    "to prove that the user's requested "
                    "behavior works. Obtain acceptance "
                    "evidence for the CURRENT edit revision "
                    "by running a specific relevant test "
                    "with "
                    "run_tests("
                    "path=<specific_test>, "
                    "purpose='acceptance'). "
                    "Do not use the full suite itself "
                    "as acceptance evidence."
                ),
            }
        )

        return (
            None,
            True,
        )

    # =========================================================
    # Need Full Regression
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
                    "Acceptance validation passed for "
                    "the current edit revision. "
                    "Now run the full regression suite "
                    "with "
                    "run_tests("
                    "path='.', "
                    "purpose='regression') "
                    "before claiming task completion."
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
                    "produce reliable evidence and "
                    "obtain new evidence."
                ),
            }
        )

        return (
            None,
            True,
        )

    # =========================================================
    # Ordinary Failure
    #
    # A regression has already had an opportunity to
    # trigger rollback above.
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
    # Recovery Escalation
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
        agent.recovery
        .recover(
            reason=(
                reason
            ),
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
# Automatic Rollback Policy
# =============================================================


def rollback_regressed_edit(
    *,
    agent,
    evidence: ValidationEvidence,
    validation_progress,
    messages: list,
) -> tuple[
    str | None,
    bool,
] | None:

    """
    Roll back the CURRENT edit revision when the SAME
    validation target became strictly worse.

    Important:

    RollbackEngine owns the physical restore.

    This function only decides whether that mechanism should
    be invoked and updates orchestration state afterward.
    """

    pipeline = getattr(
        agent,
        "validation_pipeline",
        None,
    )

    checkpoint_manager = getattr(
        agent,
        "checkpoint_manager",
        None,
    )

    rollback_engine = getattr(
        agent,
        "rollback_engine",
        None,
    )

    if (
        pipeline is None
        or checkpoint_manager is None
        or rollback_engine is None
    ):

        return None

    # =========================================================
    # Evidence Must Belong To Current Revision
    # =========================================================

    current_revision = (
        pipeline
        .state
        .edit_revision
    )

    if (
        evidence.edit_revision
        != current_revision
    ):

        return None

    # =========================================================
    # Resolve Current Revision Checkpoint
    # =========================================================

    checkpoint = (
        checkpoint_manager
        .latest_for_revision(
            evidence.edit_revision
        )
    )

    if (
        checkpoint
        is None
    ):

        return None

    if (
        not checkpoint.sealed
        or checkpoint.rolled_back
    ):

        return None

    print(
        "\n[Automatic Rollback]"
    )

    print(
        (
            "Validation regression detected: "
            f"{validation_progress.previous_failed} "
            "failed -> "
            f"{validation_progress.current_failed} "
            "failed."
        )
    )

    print(
        (
            "Validation series: "
            f"{validation_progress.validation_key}"
        )
    )

    print(
        (
            "Checkpoint: "
            f"{checkpoint.checkpoint_id}"
        )
    )

    # =========================================================
    # Physical Rollback
    # =========================================================

    rollback_result = (
        rollback_engine
        .rollback(
            checkpoint
            .checkpoint_id
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
        working_summary
        is not None
    ):

        working_summary.record_tool_result(
            tool_name=(
                "automatic_rollback"
            ),
            arguments={
                "checkpoint_id": (
                    checkpoint
                    .checkpoint_id
                ),
                "edit_revision": (
                    evidence
                    .edit_revision
                ),
                "validation_key": (
                    validation_progress
                    .validation_key
                ),
                "failed_before": (
                    validation_progress
                    .previous_failed
                ),
                "failed_after": (
                    validation_progress
                    .current_failed
                ),
            },
            result=(
                rollback_result
            ),
        )

    # =========================================================
    # Rollback Failed / Was Blocked
    # =========================================================

    if not (
        rollback_result.success
    ):

        print(
            "\n[Rollback Failed]"
        )

        print(
            rollback_result.to_llm_text()
        )

        messages.append(
            {
                "role": "user",
                "content": (
                    "Validation became worse after the "
                    "current edit, so the Harness attempted "
                    "an automatic rollback, but rollback "
                    "was blocked or failed. "
                    f"{rollback_result.to_llm_text()} "
                    "Inspect the current physical workspace "
                    "before making another modification."
                ),
            }
        )

        return (
            None,
            True,
        )

    # =========================================================
    # Rollback Is A New Workspace State
    #
    # Revision sequence remains monotonic:
    #
    # revision 4 = before
    # revision 5 = bad edit
    # revision 6 = rollback result
    #
    # Even if revision 4 and revision 6 have identical
    # physical content.
    # =========================================================

    rollback_revision = (
        pipeline
        .record_edit()
    )

    # =========================================================
    # Validation Trend Is Now Stale
    # =========================================================

    agent.progress.reset()

    # =========================================================
    # Recovery Has Made Real Progress
    # =========================================================

    agent.recovery.mark_progress()

    # =========================================================
    # Tell LLM What Deterministically Happened
    # =========================================================

    messages.append(
        {
            "role": "user",
            "content": (
                "The Harness detected that the latest "
                "comparable validation became worse and "
                "automatically rolled back the responsible "
                "edit. "
                f"Checkpoint "
                f"{checkpoint.checkpoint_id} was restored. "
                f"The restored workspace is now revision "
                f"{rollback_revision}. "
                "All previous validation evidence is stale. "
                "Inspect the restored source and choose a "
                "materially different repair strategy. "
                "Do not immediately repeat the reverted edit."
            ),
        }
    )

    print(
        "\n[Rollback Successful]"
    )

    print(
        (
            "Restored checkpoint: "
            f"{checkpoint.checkpoint_id}"
        )
    )

    print(
        (
            "New workspace revision: "
            f"{rollback_revision}"
        )
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
    Provider tool-call protocols expect every assistant tool
    call to receive a corresponding tool response.

    When plan, validation or recovery state changes midway
    through a batch, remaining calls are intentionally skipped.
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
    # Plan
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
            if (
                step.status
                in {
                    StepStatus.PENDING,
                    StepStatus.IN_PROGRESS,
                }
            )
        ]

        lines.append(
            (
                "Plan progress: "
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

        if (
            plan.is_completed()
        ):

            lines.append(
                (
                    "All plan steps are "
                    "marked complete."
                )
            )

    # =========================================================
    # Validation
    # =========================================================

    pipeline = getattr(
        agent,
        "validation_pipeline",
        None,
    )

    if (
        pipeline
        is not None
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

        lines.append(
            (
                "Acceptance evidence: "
                f"{state.acceptance_passed}."
            )
        )

        lines.append(
            (
                "Full regression evidence: "
                f"{state.full_passed}."
            )
        )

        if (
            evidence
            is not None
        ):

            lines.append(
                (
                    "Last validation: "
                    f"purpose="
                    f"{evidence.purpose.value}, "
                    f"scope="
                    f"{evidence.scope.value}, "
                    f"outcome="
                    f"{evidence.outcome.value}, "
                    f"revision="
                    f"{evidence.edit_revision}."
                )
            )

        completion = (
            evaluate_completion(
                agent
            )
        )

        lines.append(
            (
                "Completion gate: "
                f"{completion.status.value}."
            )
        )

    # =========================================================
    # Checkpoint / Rollback State
    # =========================================================

    checkpoint_manager = getattr(
        agent,
        "checkpoint_manager",
        None,
    )

    if (
        checkpoint_manager
        is not None
    ):

        checkpoints = (
            checkpoint_manager
            .all_checkpoints()
        )

        lines.append(
            (
                "Checkpoint count: "
                f"{len(checkpoints)}."
            )
        )

        if checkpoints:

            latest = (
                checkpoints[-1]
            )

            lines.append(
                (
                    "Latest checkpoint: "
                    f"{latest.checkpoint_id}, "
                    f"revision="
                    f"{latest.edit_revision}, "
                    f"path="
                    f"{latest.snapshot.path}, "
                    f"sealed="
                    f"{latest.sealed}, "
                    f"rolled_back="
                    f"{latest.rolled_back}."
                )
            )

    # =========================================================
    # Validation Failure Trend
    # =========================================================

    failed = getattr(
        agent.progress,
        "last_validation_failed_count",
        None,
    )

    validation_key = getattr(
        agent.progress,
        "last_validation_key",
        None,
    )

    if (
        failed
        == 0
    ):

        lines.append(
            (
                "Latest validation "
                "failure count: 0."
            )
        )

    elif (
        failed
        is not None
    ):

        lines.append(
            (
                "Latest validation "
                "failure count: "
                f"{failed}."
            )
        )

    if (
        validation_key
    ):

        lines.append(
            (
                "Validation trend key: "
                f"{validation_key}."
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
        working_summary
        is not None
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