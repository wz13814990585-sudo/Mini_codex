"""Atomic provider tool-batch execution and control transitions."""

from __future__ import annotations

from dataclasses import dataclass

from ..editing import EditFailureType
from ..progress import ProgressKind, ProgressSignal
from ..reason_codes import ReasonCode
from ..task_state import AgentPhase, RuntimeEventType
from .message_protocol import close_tool_batch_before_control_transition
from .tool_call_runner import ToolCallRun, ToolCallRunner
from .tool_batch_result import ToolBatchResult
from .tool_result_handlers import EditResultHandler, ValidationResultHandler


class ToolEventAdapter:
    """Translate executed tool facts into domain events and control decisions."""

    def __init__(self, call_runner):
        self.call_runner = call_runner
        self.edit_handler = EditResultHandler()
        self.validation_handler = ValidationResultHandler()

    def process(self, agent, tool_call, *, index, tool_calls, messages,
                current_plan_step, runs, evidence_items, signals):
        tool_name = tool_call.function.name
        metrics = getattr(agent, "execution_metrics", None)
        if metrics is not None:
            note = getattr(metrics, "note_step_tool_call", None)
            if callable(note):
                note()
        args_preview = str(getattr(tool_call.function, "arguments", "") or "")[:240]
        action = getattr(agent, "action_controller", None)
        self._emit_event(
            agent,
            RuntimeEventType.TOOL_STARTED,
            tool_name=tool_name,
            arguments_summary=args_preview,
            agent_step=int(getattr(metrics, "agent_steps", 0) or 0),
            phase=getattr(getattr(action, "phase", None), "value", getattr(action, "phase", None)),
        )
        run = self.call_runner.run(agent, tool_call)
        runs.append(run)
        tool_name, arguments, result = run.tool_name, run.arguments, run.result
        capabilities = (agent.registry.capabilities_for(tool_name)
                        if tool_name in getattr(agent.registry, "_tools", {}) else frozenset())
        is_edit = "code.edit" in capabilities
        if not is_edit and capabilities & {"process.run", "test.run", "service.validate", "validation.browser"}:
            previous_revision = agent.validation_pipeline.state.edit_revision
            refresh = getattr(agent, "refresh_workspace_facts", None)
            if refresh is not None:
                refresh()
            if agent.validation_pipeline.state.edit_revision != previous_revision:
                # Validators can run generators or race with an editor. Their
                # observation cannot prove the revision they changed mid-check.
                result.data["workspace_changed_during_validation"] = True
        metrics = getattr(agent, "execution_metrics", None)
        current_revision = agent.validation_pipeline.state.edit_revision
        if metrics is not None:
            metrics.record_tool(
                tool_name,
                llm_call_count=agent.token_metrics.call_count,
                arguments=arguments,
                success=result.success,
                revision=current_revision,
                capabilities=capabilities,
            )
        self._emit_normal_progress(agent, tool_name, arguments, result)
        print(f"\n[工具] {tool_name}")
        if arguments:
            print(f"[参数] {arguments}")

        if run.preparation_failed:
            self._emit_tool_blocked(
                agent, tool_name, arguments,
                failure_type="prepare_failed",
                restriction_source="prepare_failed",
                reason=str(getattr(result, "error", "") or ""),
            )
            self._emit_validation_skipped(agent, tool_name, arguments, "preparation_failed")
            agent.working_summary.record_tool_result(tool_name=tool_name, arguments={}, result=result)
            agent.plan_orchestrator.record_attempt_failure(current_plan_step)
            self._append_observation(messages, tool_call.id, result, "工具准备失败")
            signal = ProgressSignal(ProgressKind.NONE, "工具准备失败。")
            signals.append(signal)
            self._observe(agent, tool_name, signal)
            return None

        controller = getattr(agent, "action_controller", None)
        if run.restriction is not None:
            self._emit_tool_blocked(
                agent, tool_name, arguments,
                failure_type=str(run.restriction.failure_type or "restricted"),
                restriction_source=str(run.restriction.failure_type or "restriction"),
                reason=str(run.restriction.reason or ""),
            )
            self._emit_validation_skipped(
                agent, tool_name, arguments,
                str(run.restriction.failure_type or "restricted"),
            )
            if run.restriction.failure_type == "action_required_restriction":
                self._emit_event(agent, RuntimeEventType.PHASE_CHANGED, phase=AgentPhase.ACTING)
            if metrics is not None and controller is not None:
                metrics.action_required_trigger_count = controller.action_required_trigger_count
            agent.plan_orchestrator.record_attempt_failure(current_plan_step)
            self._append_observation(messages, tool_call.id, result, "工具受限")
            signal = ProgressSignal(ProgressKind.NONE, "工具调用被限制。")
            signals.append(signal)
            self._observe(agent, tool_name, signal)
            self._close(
                messages,
                tool_calls[index + 1 :],
                "执行策略限制了当前工具批次",
                run.restriction.reason,
            )
            return ToolBatchResult(
                tuple(runs), tuple(evidence_items), tuple(signals),
                restart=True, followup_message=run.restriction.reason,
            )

        if run.duplicate_blocked:
            self._emit_tool_blocked(
                agent, tool_name, arguments,
                failure_type="duplicate_blocked",
                restriction_source="duplicate_blocked",
                reason="duplicate_tool_call",
            )
            self._emit_validation_skipped(agent, tool_name, arguments, "duplicate_tool_call")
            agent.plan_orchestrator.record_attempt_failure(current_plan_step)
            if metrics is not None:
                metrics.repeated_action_count += 1
            print("\n[重复工具调用已拦截]")
            agent.validation_pipeline.state.observe_execution(
                check_id=str(arguments.get("validation_check", "")),
                tool_name=tool_name,
                execution_status="blocked",
                reason="duplicate_tool_call",
                proof_accepted=False,
            )
            agent.working_summary.record_tool_result(
                tool_name=tool_name, arguments=arguments, result=result,
                revision=current_revision,
            )
            self._append_observation(messages, tool_call.id, result, "重复工具调用已拦截")
            signal = ProgressSignal(ProgressKind.NONE, "重复工具调用未执行。")
            signals.append(signal)
            self._observe(agent, tool_name, signal)
            return None
        elif not result.success:
            agent.plan_orchestrator.record_attempt_failure(current_plan_step)
            failure_type = str(result.data.get("failure_type", "") or "")
            if failure_type in {
                "safety_blocked", "permission_denied", "workspace_conflict",
                "rollback_conflict", "missing_credential", "environment_failure",
            }:
                agent.concrete_blockers.append(
                    f"{failure_type}: {result.error or result.summary}"
                )

        recorded_revision = (
            current_revision + 1
            if is_edit and result.success
            else current_revision
        )
        agent.working_summary.record_tool_result(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            revision=recorded_revision,
        )
        if tool_name == "search_symbol" and result.success:
            agent.latest_symbol_recovery_paths = tuple(
                dict.fromkeys(
                    str(match.get("path", "")).strip()
                    for match in (result.data.get("matches", ()) or ())
                    if str(match.get("path", "")).strip()
                )
            )
        self._append_observation(messages, tool_call.id, result)
        if metrics is not None:
            telemetry = result.data.get("semantic_judge_telemetry")
            if telemetry:
                from types import SimpleNamespace
                metrics.record_semantic_judge(SimpleNamespace(**telemetry))

        retry = getattr(agent, "edit_retry", None)
        retry_message = retry.observe(tool_name, arguments, result) if retry is not None else None
        if retry_message:
            stale = str(result.data.get("edit_failure_type", result.data.get("failure_type", ""))) == EditFailureType.STALE_CONTEXT.value
            self._emit_event(
                agent,
                RuntimeEventType.RECOVERY_STARTED,
                level=1,
                failure_type="stale_context" if stale else "edit_failure",
            )
            signal = ProgressSignal(ProgressKind.NONE, "需要有界的本地编辑恢复。")
            signals.append(signal)
            self._observe(agent, tool_name, signal)
            self._close(
                messages,
                tool_calls[index + 1 :],
                "有界编辑恢复改变了下一步允许的操作",
                retry_message,
            )
            return ToolBatchResult(
                tuple(runs), tuple(evidence_items), tuple(signals),
                restart=True, followup_message=retry_message,
            )

        # Registered tools are classified only through their capabilities.  A
        # few embedding/test executors intentionally run outside a registry;
        # their structured validation result remains sufficient to dispatch the
        # result handler without reviving a tool-name fallback.
        structured_validation_result = (
            str(result.data.get("outcome", "")).casefold() in {"passed", "failed", "inconclusive"}
            and "errors" in result.data
        )
        is_validation = (bool(capabilities & {"test.run", "validation.static_web", "validation.browser", "service.validate", "validation.semantic"})
            or ("process.run" in capabilities and arguments.get("purpose") in {"acceptance", "regression"})
            or structured_validation_result
        )
        if (
            not is_validation
            and is_edit
            and not result.success
        ):
            self._emit_event(agent, RuntimeEventType.PHASE_CHANGED, phase=AgentPhase.ACTING)
        if not is_edit and hasattr(agent, "step_evidence"):
            agent.step_evidence.record(
                step_id=current_plan_step.id if current_plan_step else None,
                edit_revision=agent.validation_pipeline.state.edit_revision,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
            )

        signal = ProgressSignal(ProgressKind.OBSERVATION, "工具产生了一条观察结果。")
        if is_edit and result.success:
            if metrics is not None:
                note_p = getattr(metrics, "note_step_productive", None)
                if callable(note_p):
                    note_p()
            signal, completed = self.edit_handler.apply(
                agent, tool_name=tool_name, arguments=arguments, result=result,
                current_plan_step=current_plan_step, emit=self._emit_event,
            )
            print(f"\n[编辑已应用]\n[验证版本] {agent.validation_pipeline.state.edit_revision}")
            checkpoint_id = result.data.get("checkpoint_id")
            if checkpoint_id:
                print(f"[检查点] {checkpoint_id}")
            if completed:
                self._observe(agent, tool_name, signal)
                signals.append(signal)
                finished = self._check_completion(agent, messages, tool_calls[index + 1 :])
                if finished is not None:
                    return ToolBatchResult(
                        tuple(runs),
                        tuple(evidence_items),
                        tuple(signals),
                        early_stop=finished,
                        completion_finished=True,
                    )
                self._close(
                    messages,
                    tool_calls[index + 1 :],
                    "可机器检查的计划条件推进了当前计划",
                )
                return ToolBatchResult(tuple(runs), tuple(evidence_items), tuple(signals), restart=True)

        if tool_name == "replan" and result.data.get("replanned"):
            signal = ProgressSignal(ProgressKind.ADVANCED, "计划已修订。")

        if is_validation:
            purpose = str(arguments.get("purpose", "") or "").casefold()
            if metrics is not None and purpose in {"acceptance", "regression", ""}:
                # Executed acceptance/regression (or structured validation) advances task state.
                note_p = getattr(metrics, "note_step_productive", None)
                if callable(note_p):
                    note_p()
            handled = self.validation_handler.apply(
                agent, tool_name=tool_name, arguments=arguments, result=result,
                capabilities=capabilities, metrics=metrics, emit=self._emit_event,
            )
            if handled.evidence is not None:
                evidence_items.append(handled.evidence)
                print(f"\n[验证证据]\n版本：{handled.evidence.edit_revision}"
                      f"\n范围：{handled.evidence.scope.value}\n用途：{handled.evidence.purpose.value}"
                      f"\n结果：{handled.evidence.outcome.value}")
            signal, decision = handled.signal, handled.decision
            if handled.completed_plan and decision is not None:
                decision = type(decision)(restart=True, early_stop=decision.early_stop,
                                          followup_message=decision.followup_message,
                                          skipped_reason=decision.skipped_reason, reason_code=decision.reason_code)
            signals.append(signal)
            self._observe(agent, tool_name, signal)
            finished = self._check_completion(agent, messages, tool_calls[index + 1 :])
            if finished is not None:
                return ToolBatchResult(tuple(runs), tuple(evidence_items), tuple(signals),
                                       early_stop=finished, completion_finished=True)
            if decision is not None and (decision.early_stop or decision.restart):
                self._close(messages, tool_calls[index + 1 :],
                            decision.skipped_reason or "验证改变了智能体循环控制流",
                            decision.followup_message)
                return ToolBatchResult(tuple(runs), tuple(evidence_items), tuple(signals),
                                       restart=decision.restart, early_stop=decision.early_stop,
                                       followup_message=decision.followup_message, reason_code=decision.reason_code)
            return None

        signals.append(signal)
        self._observe(agent, tool_name, signal)
        if signal.advanced:
            finished = self._check_completion(agent, messages, tool_calls[index + 1 :])
            if finished is not None:
                return ToolBatchResult(
                    tuple(runs),
                    tuple(evidence_items),
                    tuple(signals),
                    early_stop=finished,
                    completion_finished=True,
                )

        if tool_name == "replan" and result.data.get("replanned"):
            self._close(
                messages,
                tool_calls[index + 1 :],
                "计划已变更，剩余调用仍使用旧计划",
            )
            return ToolBatchResult(tuple(runs), tuple(evidence_items), tuple(signals), restart=True)

        return None

    @staticmethod
    def _append_observation(messages, call_id, result, heading=None) -> None:
        text = result.to_llm_text()
        if heading:
            print(f"\n[{heading}]")
        print(f"\n[观察结果]\n{text}")
        messages.append({"role": "tool", "tool_call_id": call_id, "content": text})

    @staticmethod
    def _close(messages, remaining, reason, followup=None) -> None:
        close_tool_batch_before_control_transition(
            messages, remaining, reason, followup_user_message=followup
        )

    @staticmethod
    def _observe(agent, tool_name: str, signal: ProgressSignal) -> None:
        controller = getattr(agent, "action_controller", None)
        if controller is not None:
            controller.observe_action(tool_name, agent.task_progress_state(), signal)
            metrics = getattr(agent, "execution_metrics", None)
            if metrics is not None and signal.kind == ProgressKind.NONE:
                metrics.no_progress_detections += 1
            ToolEventAdapter._emit_event(
                agent,
                RuntimeEventType.TOOL_FINISHED,
                tool_name=tool_name,
                progress_kind=signal.kind.value,
                consecutive_inspections=controller.consecutive_inspections,
                consecutive_no_state_change=controller.consecutive_no_state_change,
            )

    @staticmethod
    def _emit_event(agent, kind: RuntimeEventType, **data) -> None:
        emit = getattr(agent, "apply_runtime_event", None)
        if callable(emit):
            emit(kind, **data)

    @staticmethod
    def _check_completion(agent, messages, remaining) -> str | None:
        checking = getattr(agent, "check_completion_after_batch", None)
        handling = checking() if callable(checking) else None
        if handling is None:
            return None
        if not handling.finished:
            return None
        close_tool_batch_before_control_transition(
            messages,
            remaining,
            "工具批次期间确定性完成条件已就绪",
        )
        return handling.output or ""

    @staticmethod
    def _emit_normal_progress(agent, tool_name: str, arguments: dict, result) -> None:
        emit = getattr(agent, "emit_normal_progress", None)
        if not callable(emit):
            return
        path = str(arguments.get("path", "") or "").strip()
        capabilities = (agent.registry.capabilities_for(tool_name)
                        if tool_name in getattr(agent.registry, "_tools", {}) else frozenset())
        if "file.read" in capabilities:
            emit(f"正在读取 {path or '目标'}...")
        elif "code.edit" in capabilities:
            emit(f"正在编辑 {path or '目标'}...")
        elif "test.run" in capabilities:
            emit("正在运行定向测试...")
            if result.success and result.data.get("tests_passed") is True:
                emit(f"{int(result.data.get('passed', 0) or 0)} 个测试通过。")
        elif capabilities & {"validation.static_web", "validation.browser", "service.validate"}:
            emit(f"正在验证 {path or 'Web 产物'}...")
            if result.success and result.data.get("outcome") == "passed":
                emit("验证通过。")


    @staticmethod
    def _emit_tool_blocked(
        agent,
        tool_name: str,
        arguments: dict,
        *,
        failure_type: str,
        restriction_source: str,
        reason: str = "",
    ) -> None:
        metrics = getattr(agent, "execution_metrics", None)
        if metrics is not None:
            note = getattr(metrics, "note_step_tool_blocked", None)
            if callable(note):
                note()
        action = getattr(agent, "action_controller", None)
        payload = {
            "tool_name": tool_name,
            "failure_type": failure_type,
            "reason_code": failure_type,
            "restriction_source": restriction_source,
            "phase": getattr(getattr(action, "phase", None), "value", getattr(action, "phase", None)),
            "agent_step": int(getattr(metrics, "agent_steps", 0) or 0),
            "validation_check_id": str(
                (arguments or {}).get("validation_check")
                or getattr(action, "next_required_check_id", "")
                or ""
            ),
            "contract_type": str(getattr(action, "next_contract_type", "") or ""),
            "reason": reason,
            "arguments_summary": str(arguments or "")[:240],
        }
        ToolEventAdapter._emit_event(agent, RuntimeEventType.TOOL_BLOCKED, **payload)
        recorder = getattr(agent, "trace_recorder", None)
        if recorder is None:
            return
        try:
            from ..observability.trace import TraceEventType
            blocked = getattr(TraceEventType, "TOOL_BLOCKED", None)
            if blocked is not None:
                recorder.emit(blocked, payload)
        except Exception:
            pass

    @staticmethod
    def _emit_validation_skipped(agent, tool_name: str, arguments: dict, reason: str) -> None:
        registry = getattr(agent, "registry", None)
        capabilities = (
            registry.capabilities_for(tool_name)
            if registry is not None and tool_name in getattr(registry, "_tools", {})
            else frozenset()
        )
        is_validation = bool(capabilities & {
            "test.run", "validation.static_web", "validation.browser",
            "service.validate", "validation.semantic",
        }) or (
            "process.run" in capabilities
            and arguments.get("purpose") in {"acceptance", "regression"}
        )
        if not is_validation:
            return
        recorder = getattr(agent, "trace_recorder", None)
        if recorder is None:
            return
        from ..observability.trace import TraceEventType
        recorder.emit(TraceEventType.VALIDATION_SKIPPED, {
            "check_id": str(arguments.get("validation_check", "")),
            "tool_name": tool_name,
            "execution_status": "blocked",
            "reason_code": reason,
            "proof_accepted": False,
        })
