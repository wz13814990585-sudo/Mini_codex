"""Thin coordination loop for one MiniCodex task."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time

from .message_protocol import validate_tool_message_protocol
from ..task_state import AgentPhase, RuntimeEventType


def _chat_with_heartbeat(agent, *, messages: list, tools: list):
    validate_tool_message_protocol(messages)
    interval = max(0.0, float(getattr(agent, "status_interval_seconds", 15.0)))
    print("\n[LLM] Waiting for model response...")
    if interval == 0:
        return agent.llm.chat(messages=messages, tools=tools)

    stopped = threading.Event()
    started = time.monotonic()

    def report_wait() -> None:
        while not stopped.wait(interval):
            print(
                f"[LLM] Still working ({int(time.monotonic() - started)}s elapsed)...",
                flush=True,
            )

    reporter = threading.Thread(target=report_wait, daemon=True)
    reporter.start()
    try:
        return agent.llm.chat(messages=messages, tools=tools)
    finally:
        stopped.set()
        reporter.join(timeout=0.1)
        print(f"[LLM] Response received after {time.monotonic() - started:.1f}s.")


@dataclass(frozen=True)
class _PreparedTurn:
    task_max_steps: int
    remaining_steps: int
    current_plan_step: object | None
    terminal_output: str | None = None


def _prepare_turn(agent, *, step: int, task_max_steps: int, messages: list) -> _PreparedTurn:
    """Apply bounded runtime policy and expose one stable turn snapshot."""

    agent.task_steps_consumed = step
    task_max_steps = int(getattr(agent, "task_max_steps", task_max_steps))
    remaining = task_max_steps - step
    escalation = agent.runtime_control.should_escalate(agent, remaining_steps=remaining)
    if escalation and agent.runtime_control.escalate(agent, reason=escalation):
        task_max_steps = int(agent.task_max_steps)
        remaining = task_max_steps - step
        agent.apply_runtime_event(
            RuntimeEventType.MODE_ESCALATED,
            mode=agent.execution_policy.mode,
            reason=escalation,
        )
        if agent.execution_policy.use_plan:
            agent.activate_late_plan(reason=escalation)

    late_plan_reason = agent.runtime_control.should_activate_plan(agent)
    if late_plan_reason:
        agent.runtime_control.enable_planning(agent)
        agent.activate_late_plan(reason=late_plan_reason)
    if remaining <= 0:
        return _PreparedTurn(task_max_steps, 0, None)

    print(f"\n[Agent Step {step + 1}/{task_max_steps}]")
    plan_turn = agent.plan_orchestrator.begin_turn(agent)
    current = plan_turn.current_step
    if current is not None:
        print(f"\n[Current Plan Step] {current.id}. {current.description}")
        print(f"[Step Failures] {current.attempts}/{agent.max_step_attempts}")
    if plan_turn.followup_message:
        print("\n[Step Recovery]")
        print(plan_turn.followup_message)
        messages.append({"role": "user", "content": plan_turn.followup_message})
    if not plan_turn.can_continue:
        handled = agent.completion_handler.handle_incomplete(
            agent, reason=plan_turn.terminal_reason or "Plan recovery could not continue."
        )
        return _PreparedTurn(
            task_max_steps, remaining, current, handled.output or "Task incomplete."
        )

    controller = getattr(agent, "action_controller", None)
    prepared_validation = None
    prepare_validation = getattr(agent, "prepare_next_validation_check", None)
    if callable(prepare_validation):
        prepared_validation = prepare_validation()
    check, resolution = prepared_validation or (None, None)
    validation_paths_for = getattr(agent, "validation_paths_for", None)
    validation_paths = (validation_paths_for(check) if callable(validation_paths_for) else
                        tuple(getattr(agent.task_state, "relevant_paths", ()) or ()))
    if controller is not None:
        controller.update_context(
            state=agent.task_progress_state(remaining),
            policy=agent.execution_policy,
            remaining_budget=remaining,
            acceptance_missing=None,
            next_required_check_id=getattr(check, "id", ""),
            validator_resolution_status=getattr(resolution, "status", ""),
            unresolved_reason=getattr(resolution, "reason", ""),
            validation_paths=validation_paths,
        )

    finalization = getattr(agent, "finalization", None)
    if (
        finalization is not None
        and remaining < task_max_steps
        and finalization.enter_if_needed(remaining, agent.execution_policy)
    ):
        print("\n[Finalization Mode]")
        agent.apply_runtime_event(RuntimeEventType.PHASE_CHANGED, phase=AgentPhase.FINALIZING)
        finalization.allow_proof_inspection = (
            getattr(getattr(resolution, "status", ""), "value", getattr(resolution, "status", ""))
            == "target_unresolved"
        )
        if agent.active_plan is not None:
            current, completed = agent.plan_orchestrator.reconcile(agent)
            if completed:
                print(
                    "Final reconciliation completed steps: "
                    + ", ".join(str(step_id) for step_id in completed)
                )

    pressure = agent.context_budget.pressure
    print("\n[Context Budget]")
    print(f"Last Prompt Tokens: {agent.context_budget.last_prompt_tokens}")
    print(f"Usage: {agent.context_budget.usage_ratio:.1%}")
    print(f"Pressure: {pressure.value}")
    return _PreparedTurn(task_max_steps, remaining, current)


def _record_model_usage(agent, response) -> None:
    agent.token_metrics.record(response.usage)
    metrics = getattr(agent, "execution_metrics", None)
    if metrics is not None:
        metrics.observe_llm(
            call_count=agent.token_metrics.call_count,
            total_prompt_tokens=agent.token_metrics.total.prompt_tokens,
        )
    agent.context_budget.observe(response.usage.prompt_tokens)
    print("\n[Token Usage]")
    print(f"Prompt: {response.usage.prompt_tokens}")
    print(f"Completion: {response.usage.completion_tokens}")
    print(f"Total: {response.usage.total_tokens}")
    print(f"Task Total: {agent.token_metrics.total.total_tokens}")
    print(f"Context Pressure: {agent.context_budget.pressure.value}")


def _apply_action_pressure(agent, messages: list) -> None:
    controller = getattr(agent, "action_controller", None)
    policy = getattr(agent, "execution_policy", None)
    if controller is None or policy is None or not controller.update_pressure(policy):
        return
    agent.apply_runtime_event(RuntimeEventType.PHASE_CHANGED, phase=AgentPhase.ACTING)
    metrics = getattr(agent, "execution_metrics", None)
    if metrics is not None:
        metrics.action_required_trigger_count = controller.action_required_trigger_count
    print("\n[ACTION_REQUIRED]")
    print(controller.INSTRUCTION)
    messages.append({"role": "user", "content": controller.INSTRUCTION})


def run_agent_loop(agent, user_input: str) -> str:
    """Coordinate state → context → decision → action → event until terminal."""

    ensure_runtime = getattr(agent, "ensure_runtime_started", None)
    if callable(ensure_runtime):
        ensure_runtime(user_input)
    messages = [{"role": "user", "content": user_input}]
    task_max_steps = int(getattr(agent, "task_max_steps", agent.max_steps))

    for step in range(int(getattr(agent, "configured_max_steps", task_max_steps))):
        ready = agent.completion_handler.check_after_batch(agent)
        if ready.finished:
            return ready.output or ""

        prepared = _prepare_turn(
            agent, step=step, task_max_steps=task_max_steps, messages=messages
        )
        task_max_steps = prepared.task_max_steps
        if prepared.terminal_output is not None:
            return prepared.terminal_output
        if prepared.remaining_steps <= 0:
            break

        turn = agent.turn_builder.build(
            agent,
            history=messages,
            user_input=user_input,
            current_plan_step=prepared.current_plan_step,
            remaining_agent_steps=prepared.remaining_steps,
        )
        metrics = getattr(agent, "execution_metrics", None)
        if metrics is not None:
            metrics.agent_steps = step + 1
        llm_response = _chat_with_heartbeat(
            agent, messages=turn.messages, tools=turn.tools
        )
        _record_model_usage(agent, llm_response)
        response = llm_response.message
        tool_calls = list(getattr(response, "tool_calls", None) or ())

        if not tool_calls:
            content = getattr(response, "content", None) or ""
            handled = agent.completion_handler.handle_text_response(
                agent,
                content=content,
                remaining_steps=task_max_steps - step - 1,
            )
            if handled.finished:
                return handled.output or ""
            messages.append(
                {"role": "assistant", "content": content or "No tool action was taken."}
            )
            if handled.followup_instruction:
                messages.append({"role": "user", "content": handled.followup_instruction})
            continue

        batch = agent.tool_batch_runner.run(
            agent, response, messages, current_plan_step=prepared.current_plan_step
        )
        if batch.early_stop is not None:
            if batch.completion_finished:
                return batch.early_stop
            handled = agent.completion_handler.handle_control_stop(
                agent, reason=batch.early_stop, reason_code=batch.reason_code
            )
            return handled.output or "Task incomplete."
        if batch.restart:
            continue

        ready = agent.completion_handler.check_after_batch(agent)
        if ready.finished:
            return ready.output or ""
        _apply_action_pressure(agent, messages)

    if getattr(agent, "active_plan", None) is not None:
        agent.reconcile_plan_progress()
    agent.apply_runtime_event(RuntimeEventType.BUDGET_EXHAUSTED)
    exhausted = agent.completion_handler.handle_budget_exhausted(
        agent, reason="The maximum number of agent steps was reached."
    )
    return exhausted.output or "Task incomplete."
