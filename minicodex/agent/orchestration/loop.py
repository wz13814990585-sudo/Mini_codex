"""Thin coordination loop for one MiniCodex task."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time

from .message_protocol import validate_tool_message_protocol
from ..task_state import AgentPhase, RuntimeEventType
from ..reason_codes import ReasonCode


def _chat_with_heartbeat(agent, *, messages: list, tools: list):
    validate_tool_message_protocol(messages)
    interval = max(0.0, float(getattr(agent, "status_interval_seconds", 15.0)))
    print("\n[模型] 正在等待模型响应...")
    if interval == 0:
        return agent.llm.chat(messages=messages, tools=tools)

    stopped = threading.Event()
    started = time.monotonic()

    def report_wait() -> None:
        while not stopped.wait(interval):
            print(
                f"[模型] 仍在处理中（已用时 {int(time.monotonic() - started)} 秒）...",
                flush=True,
            )

    reporter = threading.Thread(target=report_wait, daemon=True)
    reporter.start()
    try:
        return agent.llm.chat(messages=messages, tools=tools)
    finally:
        stopped.set()
        reporter.join(timeout=0.1)
        print(f"[模型] 已收到响应，用时 {time.monotonic() - started:.1f} 秒。")


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

    print(f"\n[Agent 步骤 {step + 1}/{task_max_steps}]")
    plan_turn = agent.plan_orchestrator.begin_turn(agent)
    current = plan_turn.current_step
    if current is not None:
        print(f"\n[当前计划步骤] {current.id}. {current.description}")
        print(f"[步骤失败次数] {current.attempts}/{agent.max_step_attempts}")
    if plan_turn.followup_message:
        print("\n[步骤恢复]")
        print(plan_turn.followup_message)
        messages.append({"role": "user", "content": plan_turn.followup_message})
    if not plan_turn.can_continue:
        handled = agent.completion_handler.handle_incomplete(
            agent, reason=plan_turn.terminal_reason or "计划恢复无法继续。"
        )
        return _PreparedTurn(
            task_max_steps, remaining, current, handled.output or "任务未完成。"
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
        print("\n[收尾模式]")
        agent.apply_runtime_event(RuntimeEventType.PHASE_CHANGED, phase=AgentPhase.FINALIZING)
        finalization.allow_proof_inspection = (
            getattr(getattr(resolution, "status", ""), "value", getattr(resolution, "status", ""))
            == "target_unresolved"
        )
        if agent.active_plan is not None:
            current, completed = agent.plan_orchestrator.reconcile(agent)
            if completed:
                print(
                    "最终核对已完成的步骤："
                    + ", ".join(str(step_id) for step_id in completed)
                )

    pressure = agent.context_budget.pressure
    print("\n[上下文预算]")
    print(f"上次提示词 Token：{agent.context_budget.last_prompt_tokens}")
    print(f"使用率：{agent.context_budget.usage_ratio:.1%}")
    print(f"压力：{pressure.value}")
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
    print("\n[Token 用量]")
    print(f"提示词：{response.usage.prompt_tokens}")
    print(f"补全：{response.usage.completion_tokens}")
    print(f"合计：{response.usage.total_tokens}")
    print(f"任务累计：{agent.token_metrics.total.total_tokens}")
    print(f"上下文压力：{agent.context_budget.pressure.value}")


def _apply_action_pressure(agent, messages: list) -> None:
    controller = getattr(agent, "action_controller", None)
    policy = getattr(agent, "execution_policy", None)
    if controller is None or policy is None or not controller.update_pressure(policy):
        return
    agent.apply_runtime_event(RuntimeEventType.PHASE_CHANGED, phase=AgentPhase.ACTING)
    metrics = getattr(agent, "execution_metrics", None)
    if metrics is not None:
        metrics.action_required_trigger_count = controller.action_required_trigger_count
    print("\n[需要采取行动]")
    print(controller.INSTRUCTION)
    messages.append({"role": "user", "content": controller.INSTRUCTION})


def run_agent_loop(agent, user_input: str) -> str:
    """Coordinate state → context → decision → action → event until terminal."""

    ensure_runtime = getattr(agent, "ensure_runtime_started", None)
    if callable(ensure_runtime):
        ensure_runtime(user_input)
    messages = [{"role": "user", "content": user_input}]
    task_max_steps = int(getattr(agent, "task_max_steps", agent.max_steps))
    reported_validation_attempts: set[tuple] = set()

    for step in range(int(getattr(agent, "configured_max_steps", task_max_steps))):
        execute_validations = getattr(agent, "execute_resolved_validations", None)
        executions = execute_validations() if callable(execute_validations) else ()
        if executions:
            agent.sync_requirements_state()
            agent.plan_orchestrator.reconcile(agent)
        for execution in executions:
            key = (
                execution.check_id,
                agent.validation_pipeline.state.edit_revision,
                execution.state.value,
                execution.reason,
            )
            if key in reported_validation_attempts:
                continue
            reported_validation_attempts.add(key)
            if execution.state.value == "failed":
                messages.append({
                    "role": "user",
                    "content": (
                        f"Harness 已执行必需检查 {execution.check_id}，验证失败。"
                        f"请根据以下实际结果做针对性修复：{execution.reason}"
                    ),
                })
            elif execution.state.value == "inconclusive":
                messages.append({
                    "role": "user",
                    "content": (
                        f"Harness 执行检查 {execution.check_id} 时环境/执行无定论："
                        f"{execution.reason}。仅检查该执行问题，不要改写验证目标。"
                    ),
                })
            elif execution.state.value == "unresolved":
                messages.append({
                    "role": "user",
                    "content": (
                        f"检查 {execution.check_id} 的目标尚未解析：{execution.reason}"
                        "。只允许一次最小仓库探查；Harness 将随后重新解析。"
                    ),
                })
        blocked = next((item for item in executions if item.state.value == "blocked"), None)
        if (
            blocked is not None
            and (agent.validation_pipeline.state.has_edit or step > 0)
        ):
            handled = agent.completion_handler.handle_control_stop(
                agent, reason=blocked.reason, reason_code=ReasonCode.BLOCKED
            )
            return handled.output or "任务被验证能力阻塞。"
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
                {"role": "assistant", "content": content or "未采取工具动作。"}
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
            return handled.output or "任务未完成。"
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
        agent, reason="已达到 Agent 步骤上限。"
    )
    return exhausted.output or "任务未完成。"
