"""Agent execution loop."""

import re
import threading
import time

from .control_decision import ControlDecision
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
from .message_protocol import (
    close_tool_batch_before_control_transition,
    validate_tool_message_protocol,
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

                agent.no_progress_policy.start_step(
                    current_plan_step.id
                )

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
        # System Prompt
        # =====================================================

        system_prompt = (
            agent._build_system_prompt(
                user_input=user_input,
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

        llm_response = _chat_with_heartbeat(
            agent,
            messages=llm_messages,
            tools=(
                agent.registry
                .get_schemas()
            ),
        )

        # =====================================================
        # Token Metrics
        # =====================================================

        agent.token_metrics.record(
            llm_response.usage
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

            # =================================================
            # GATE 1:
            # Active Plan Must Be Complete
            #
            # This MUST occur before CompletionGate READY.
            # =================================================

            if (
                active_plan_incomplete(
                    agent
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

            # =================================================
            # GATE 2:
            # Editing Task Fully Validated
            # =================================================

            if (
                completion.can_complete
            ):

                return (
                    content
                    or summarize_agent_stop(
                        agent,
                        (
                            "Task completed with "
                            "acceptance evidence, "
                            "full regression evidence, "
                            "and a completed plan."
                        ),
                    )
                )

            # =================================================
            # An Edit Exists But Evidence Is Incomplete
            # =================================================

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

                    # =========================================
                    # Acceptance Missing
                    # =========================================

                    if (
                        completion.status
                        == (
                            CompletionStatus
                            .NEEDS_ACCEPTANCE
                        )
                    ):

                        reminder = acceptance_evidence_reminder(
                            agent,
                            prefix=(
                                "The current edit revision cannot "
                                "complete yet because acceptance "
                                "evidence is missing. "
                            ),
                        )

                    # =========================================
                    # Full Regression Missing
                    # =========================================

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

            # =================================================
            # Read-Only / Informational Task
            #
            # No successful edit exists and no plan is pending.
            # =================================================

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
            # Deterministic Recovery Restriction
            # =================================================

            restriction_reason = (
                agent.no_progress_policy
                .restriction_reason(
                    tool_name,
                    arguments,
                )
            )

            if restriction_reason is not None:
                result = ToolResult(
                    success=False,
                    summary=(
                        f"Tool call '{tool_name}' was blocked "
                        "while no-progress recovery is active."
                    ),
                    data={
                        "tool_name": tool_name,
                        "failure_type": (
                            "no_progress_restriction"
                        ),
                    },
                    error=restriction_reason,
                )

                if current_plan_step:
                    current_plan_step.increment_attempt()

                observation_text = result.to_llm_text()
                print("\n[No-Progress Tool Restriction]")
                print(f"\n[Observation]\n{observation_text}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": observation_text,
                    }
                )
                close_tool_batch_before_control_transition(
                    messages,
                    response.tool_calls[
                        tool_index + 1:
                    ],
                    "no-progress recovery restricted reconnaissance",
                    followup_user_message=restriction_reason,
                )
                restart_agent_loop = True
                break

            # =================================================
            # 2. Duplicate Tool Policy
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
                # Editing tools pass through
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

                print(
                    "\n[Edit Applied]"
                )

                agent.progress.mark_meaningful_progress()

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
                        response.tool_calls[
                            tool_index + 1:
                        ],
                        (
                            "machine-checkable plan criteria "
                            "advanced the active plan"
                        ),
                    )
                    restart_agent_loop = True
                    break

            progress_decision = (
                agent.no_progress_policy
                .observe_tool_result(
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                    step_id=(
                        current_plan_step.id
                        if current_plan_step
                        else None
                    ),
                    context_critical=(
                        agent.context_budget
                        .pressure.value
                        == "critical"
                    ),
                )
            )

            if progress_decision.stuck:
                # The current implementation may already satisfy one or
                # more explicit predicates. Advance those steps before
                # falling back to generic stuck recovery.
                reconciliation = agent.reconcile_plan_progress()
                reconciled_steps = reconciliation["completed"]

                if reconciled_steps:
                    print("\n[Plan Reconciliation Before Recovery]")
                    print(
                        "Machine criteria completed steps: "
                        + ", ".join(
                            str(item["step_id"])
                            for item in reconciled_steps
                        )
                    )
                    close_tool_batch_before_control_transition(
                        messages,
                        response.tool_calls[tool_index + 1:],
                        (
                            "machine-checkable plan criteria advanced "
                            "the active plan before stuck recovery"
                        ),
                    )
                    restart_agent_loop = True
                    break

                recovery_instruction = (
                    agent.no_progress_policy.RECOVERY_INSTRUCTION
                )
                print("\n[No-Progress Recovery]")
                print(progress_decision.reason)
                close_tool_batch_before_control_transition(
                    messages,
                    response.tool_calls[
                        tool_index + 1:
                    ],
                    "deterministic no-progress recovery started",
                    followup_user_message=recovery_instruction,
                )
                restart_agent_loop = True
                break

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

                    close_tool_batch_before_control_transition(
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
                        apply_validation_evidence(
                            agent=agent,
                            evidence=evidence,
                        )
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
                            response.tool_calls[
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

                    close_tool_batch_before_control_transition(
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

                close_tool_batch_before_control_transition(
                    messages,
                    response.tool_calls[
                        tool_index + 1:
                    ],
                    (
                        "progress recovery "
                        "restarted the loop"
                    ),
                    followup_user_message=recovery_message,
                )

                restart_agent_loop = True

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
        #
        # Validation READY alone is not enough.
        # An active plan must also be complete.
        # =====================================================

        completion = (
            evaluate_completion(
                agent
            )
        )

        if (
            completion.can_complete
            and not (
                active_plan_incomplete(
                    agent
                )
            )
        ):

            return summarize_agent_stop(
                agent,
                (
                    "Task completed: "
                    "the current edit revision "
                    "has acceptance evidence "
                    "and full regression evidence, "
                    "and the implementation plan "
                    "is complete."
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

    Only the same:

        purpose
        +
        scope
        +
        path

    may be compared.

    Revision is deliberately NOT part of this key because
    we need to compare the same test across revisions.

    Example:

        revision 1
        acceptance|targeted|tests/test_feature.py
        5 failed

        ↓ edit

        revision 2
        acceptance|targeted|tests/test_feature.py
        8 failed

    This is a valid cross-revision comparison.
    """

    return (
        f"{evidence.purpose.value}"
        f"|{evidence.scope.value}"
        f"|{evidence.path or ''}"
    )


# =============================================================
# Plan Completion Policy
# =============================================================


def active_plan_incomplete(
    agent,
) -> bool:

    """
    Return True when an active implementation plan still
    contains unfinished steps.
    """

    plan = getattr(
        agent,
        "active_plan",
        None,
    )

    return bool(
        plan
        and not plan.is_completed()
    )


def acceptance_evidence_reminder(
    agent,
    *,
    prefix: str = (
        "Regression validation is not enough to prove that the "
        "user's requested behavior works. "
    ),
) -> str:
    """Choose acceptance guidance from registered tools and artifacts."""

    registry = getattr(agent, "registry", None)
    registered = set(getattr(registry, "_tools", {}) or {})
    candidate_paths: list[str] = []

    awareness = getattr(agent, "git_awareness", None)
    if awareness is not None:
        try:
            candidate_paths.extend(
                awareness.task_state().agent_touched_files
            )
        except Exception:
            pass

    plan = getattr(agent, "active_plan", None)
    if plan is not None:
        for step in plan.all_steps():
            for criterion in getattr(step, "acceptance_criteria", []) or []:
                path = str(criterion.get("path", "")).strip()
                if path:
                    candidate_paths.append(path)

    request = str(getattr(agent, "active_user_request", "") or "")
    candidate_paths.extend(
        re.findall(r"[\w./\\-]+\.html\b", request, flags=re.IGNORECASE)
    )
    html_path = next(
        (path for path in candidate_paths if path.lower().endswith(".html")),
        None,
    )

    if html_path and "validate_static_web" in registered:
        return (
            prefix
            + "Obtain targeted acceptance evidence for the CURRENT edit "
            "revision with "
            f"validate_static_web(path={html_path!r})."
        )

    if "run_tests" in registered:
        return (
            prefix
            + "Obtain acceptance evidence for the CURRENT edit revision "
            "with a specific relevant test using "
            "run_tests(path=<specific_test>, purpose='acceptance'). Do "
            "not use the full suite itself as acceptance evidence."
        )

    if "run_command" in registered:
        return (
            prefix
            + "Run a specific command that demonstrates the requested "
            "behavior using run_command(command=<acceptance_command>, "
            "purpose='acceptance')."
        )

    return (
        prefix
        + "Obtain explicit acceptance evidence for the CURRENT edit "
        "revision using an available targeted validator."
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
    """
    Raw CompletionGate result.

    Kept for compatibility with existing Stage 9 tests.

    This does NOT include implementation-plan policy.
    """

    return (
        evaluate_completion(
            agent
        )
        .can_complete
    )


def can_finish_edit_task(
    agent,
) -> bool:
    """
    Final orchestration-level completion decision.

    Editing task completion requires:

        plan complete or no plan
        +
        acceptance PASS
        +
        full regression PASS
    """

    if (
        active_plan_incomplete(
            agent
        )
    ):

        return False

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
    messages: list | None = None,
) -> ControlDecision:

    """
    Convert ValidationEvidence into an Agent-level control decision.

    ``messages`` is accepted for source compatibility but is deliberately
    never mutated. Only the orchestration loop may commit provider-history
    transitions.

    ValidationPipeline:
        What does this result mean?

    ProgressController:
        Is the SAME validation target improving,
        unchanged or regressing?

    RollbackEngine:
        Restore the prior physical state.

    CompletionGate:
        Does current revision have enough evidence?

    AgentLoop:
        What should happen next?
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
    #
    # Stage 10.5:
    # Revision is explicitly passed to ProgressController.
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
            edit_revision=(
                evidence.edit_revision
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
    # Automatic Rollback
    #
    # Requirements:
    #
    # 1. Current validation FAILED
    # 2. Same test series became worse
    # 3. Regression crossed an edit revision
    #
    # Same-revision fluctuation MUST NOT automatically undo
    # code because it may represent flaky/environmental tests.
    # =========================================================

    if (
        evidence.outcome
        == ValidationOutcome.FAILED
        and (
            validation_progress.status
            == ValidationStatus.REGRESSED
        )
        and (
            validation_progress
            .crossed_revision
        )
    ):

        rollback_control = (
            rollback_regressed_edit(
                agent=agent,
                evidence=evidence,
                validation_progress=validation_progress,
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
    #
    # This does NOT itself terminate the task because the
    # active plan may still be incomplete.
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

        return ControlDecision()

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

        return ControlDecision(
            restart=True,
            followup_message=acceptance_evidence_reminder(agent),
            skipped_reason=(
                "validation requires acceptance evidence"
            ),
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

        return ControlDecision(
            restart=True,
            followup_message=(
                "Acceptance validation passed for the current edit "
                "revision. Now run the full regression suite with "
                "run_tests(path='.', purpose='regression') before "
                "claiming task completion."
            ),
            skipped_reason=(
                "validation requires full regression evidence"
            ),
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

        return ControlDecision(
            restart=True,
            followup_message=(
                "Validation was inconclusive. Do not treat it as "
                "either a code failure or successful validation. "
                "Inspect why validation could not produce reliable "
                "evidence and obtain new evidence."
            ),
            skipped_reason="validation was inconclusive",
        )

    # =========================================================
    # Ordinary Failure
    #
    # Cross-revision regression already had an opportunity
    # to trigger rollback above.
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

        return ControlDecision()

    # =========================================================
    # No Stall
    # =========================================================

    if not (
        validation_progress
        .stalled
    ):

        return ControlDecision()

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

        return ControlDecision(
            early_stop=(
                "Agent stopped because "
                "validation remained stalled."
            ),
        )

    return ControlDecision(
        restart=True,
        followup_message=recovery_message,
        skipped_reason="validation recovery restarted the loop",
    )


# =============================================================
# Automatic Rollback Policy
# =============================================================


def rollback_regressed_edit(
    *,
    agent,
    evidence: ValidationEvidence,
    validation_progress,
    messages: list | None = None,
) -> ControlDecision | None:

    """
    Roll back the CURRENT edit revision when the SAME
    validation target became strictly worse across revisions.

    Example:

        revision 1:
        5 failed

        ↓ edit

        revision 2:
        8 failed

        → revision 2 may be rolled back.

    But:

        revision 2:
        5 failed
        ↓ rerun without edit
        8 failed

        → MUST NOT automatically rollback.

    RollbackEngine owns physical restoration.

    This function owns orchestration policy.
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
    # Defensive Cross-Revision Guard
    #
    # apply_validation_evidence already checks this, but this
    # helper also protects itself when called directly.
    # =========================================================

    if not (
        validation_progress
        .crossed_revision
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

    if (
        validation_progress
        .current_revision
        != current_revision
    ):

        return None

    # =========================================================
    # Resolve Checkpoint Protecting Current Revision
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
            "Revision transition: "
            f"{validation_progress.previous_revision} "
            "-> "
            f"{validation_progress.current_revision}"
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
                "previous_revision": (
                    validation_progress
                    .previous_revision
                ),
                "current_revision": (
                    validation_progress
                    .current_revision
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
    # Rollback Failed / Blocked
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

        return ControlDecision(
            restart=True,
            followup_message=(
                "Validation became worse after the current edit, so "
                "the Harness attempted an automatic rollback, but "
                "rollback was blocked or failed. "
                f"{rollback_result.to_llm_text()} Inspect the current "
                "physical workspace before making another modification."
            ),
            skipped_reason="automatic rollback failed",
        )

    # =========================================================
    # Rollback Creates A New Monotonic Workspace Revision
    #
    # revision 4 = A
    # revision 5 = bad B
    # revision 6 = rollback → A
    #
    # revision is an event identity, not an undo cursor.
    # =========================================================

    rollback_revision = (
        pipeline
        .record_edit()
    )

    # =========================================================
    # Old Validation Trends Are Stale
    # =========================================================

    agent.progress.reset()

    # =========================================================
    # Recovery Has Made Deterministic Progress
    # =========================================================

    agent.recovery.mark_progress()

    no_progress_policy = getattr(
        agent,
        "no_progress_policy",
        None,
    )
    if no_progress_policy is not None:
        no_progress_policy.mark_progress(
            "rollback changed workspace revision"
        )

    # =========================================================
    # Describe What Happened To The Loop
    # =========================================================

    followup_message = (
        "The Harness detected that the latest comparable validation "
        "became worse across an edit revision and automatically rolled "
        "back the responsible edit. "
        f"Checkpoint {checkpoint.checkpoint_id} was restored. "
        f"The restored workspace is now revision {rollback_revision}. "
        "All previous validation evidence is stale. Inspect the restored "
        "source and choose a materially different repair strategy. Do "
        "not immediately repeat the reverted edit."
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

    return ControlDecision(
        restart=True,
        followup_message=followup_message,
        skipped_reason="automatic rollback changed the workspace revision",
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

        lines.append(
            (
                "Plan completion gate: "
                f"{not active_plan_incomplete(agent)}."
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
    # Validation Trend
    # =========================================================

    progress = getattr(
        agent,
        "progress",
        None,
    )

    if (
        progress
        is not None
    ):

        failed = getattr(
            progress,
            "last_validation_failed_count",
            None,
        )

        validation_key = getattr(
            progress,
            "last_validation_key",
            None,
        )

        validation_revision = getattr(
            progress,
            "last_validation_revision",
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

        if (
            validation_revision
            is not None
        ):

            lines.append(
                (
                    "Validation trend revision: "
                    f"{validation_revision}."
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
