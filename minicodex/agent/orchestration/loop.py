"""Agent execution loop."""

import threading
import time

from .message_protocol import (
    validate_tool_message_protocol,
)
from .tool_batch_runner import EDIT_TOOL_NAMES


# =============================================================
# Constants
# =============================================================


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

    for agent_step in range(int(getattr(agent, "configured_max_steps", task_max_steps))):

        agent.task_steps_consumed = agent_step
        task_max_steps = int(getattr(agent, "task_max_steps", task_max_steps))
        remaining_before_turn = task_max_steps - agent_step
        escalation_reason = agent.runtime_control.should_escalate(
            agent, remaining_steps=remaining_before_turn
        )
        if escalation_reason and agent.runtime_control.escalate(agent, reason=escalation_reason):
            task_max_steps = int(agent.task_max_steps)
            if agent.execution_policy.use_plan:
                agent.activate_late_plan(reason=escalation_reason)
        late_plan_reason = agent.runtime_control.should_activate_plan(agent)
        if late_plan_reason:
            agent.runtime_control.enable_planning(agent)
            agent.activate_late_plan(reason=late_plan_reason)
        if agent_step >= task_max_steps:
            break

        print(
            f"\n[Agent Step "
            f"{agent_step + 1}/"
            f"{task_max_steps}]"
        )

        plan_turn = agent.plan_orchestrator.begin_turn(agent)
        current_plan_step = plan_turn.current_step
        if current_plan_step is not None:
            print(
                f"\n[Current Plan Step] {current_plan_step.id}. "
                f"{current_plan_step.description}"
            )
            print(
                f"[Step Failures] {current_plan_step.attempts}/"
                f"{agent.max_step_attempts}"
            )
        if plan_turn.followup_message:
            print("\n[Step Recovery]")
            print(plan_turn.followup_message)
            messages.append({"role": "user", "content": plan_turn.followup_message})
        if not plan_turn.can_continue:
            handling = agent.completion_handler.handle_incomplete(
                agent,
                reason=plan_turn.terminal_reason or "Plan recovery could not continue.",
            )
            return handling.output or "Task incomplete."

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
                current_plan_step, completed_steps = agent.plan_orchestrator.reconcile(agent)
                if completed_steps:
                    print(
                        "Final reconciliation completed steps: "
                        + ", ".join(str(step_id) for step_id in completed_steps)
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

        batch = agent.tool_batch_runner.run(
            agent,
            response,
            messages,
            current_plan_step=current_plan_step,
        )
        if batch.early_stop is not None:
            if batch.completion_finished:
                return batch.early_stop
            handling = agent.completion_handler.handle_control_stop(
                agent,
                reason=batch.early_stop,
                reason_code=batch.reason_code,
            )
            return handling.output or "Task incomplete."
        if batch.restart:
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
