"""Build phase-specific context from deterministic task facts."""

from __future__ import annotations

from ..editing import EditStrategyHint
from ..task_state import AgentPhase


_PHASE_LABELS = {
    AgentPhase.INSPECTING: "探查中",
    AgentPhase.ACTING: "执行中",
    AgentPhase.VALIDATING: "验证中",
    AgentPhase.FIXING: "修复中",
    AgentPhase.FINALIZING: "收尾中",
    AgentPhase.DONE: "已完成",
    AgentPhase.BLOCKED: "已阻塞",
}


def _phase_display(phase: AgentPhase) -> str:
    label = _PHASE_LABELS.get(phase, phase.value)
    return f"{label} [{phase.name}]"


class ContextBuilder:
    """Keep the model focused on the single next useful action."""

    def __init__(self, edit_strategy: EditStrategyHint | None = None) -> None:
        self.edit_strategy = edit_strategy or EditStrategyHint()

    def build(self, agent, *, current_plan_step, remaining_agent_steps: int) -> str:
        refresh_workspace = getattr(agent, "refresh_workspace_facts", None)
        if refresh_workspace is not None:
            refresh_workspace()
        policy = getattr(agent, "execution_policy", None)
        if policy is None or not policy.compact_context:
            agent._refresh_repo_map(force=False)
        refresh = getattr(agent, "refresh_runtime_context", None)
        if callable(refresh):
            refresh()
        state = agent.task_progress_state(remaining_agent_steps)
        targets = tuple(state.relevant_paths or state.target_paths)
        ledger = agent.validation_pipeline.state
        missing = tuple(check for check in ledger.plan.checks if check.required and not ledger.proof(check.id))
        next_check = missing[0] if missing else None
        sections = [
            f"任务：{state.user_request or getattr(agent, 'active_user_request', '')}",
            (
                f"当前阶段：{_phase_display(state.phase)}；"
                f"目标：{', '.join(targets) or '未明确'}；"
                f"剩余步骤：{remaining_agent_steps}。"
            ),
            "证据优先级：当前工作区/工具证据 > 明确需求 > 运行时投影 > 记忆 > 假设。",
        ]
        unit = state.work_unit
        if unit and not unit.closed:
            sections.append(
                f"工作单元 {unit.id}：路径={unit.edited_paths}；"
                f"编辑={unit.edits}/{unit.max_edits}；"
                f"里程碑={', '.join(unit.milestone_check_ids) or '待解析'}。"
            )
        session = getattr(agent, "workspace_session", None)
        if state.phase == AgentPhase.INSPECTING:
            sections.append("先定位 → 再扩展 → 动手前只阅读最小相关代码。")
            repo_fragment = str(getattr(agent, "repo_map_text", "") or "")[:1800]
            if repo_fragment:
                sections.append("仓库地图：\n" + repo_fragment)
        elif state.phase == AgentPhase.ACTING:
            sections.append(self.edit_strategy.render(agent.workspace, targets[0] if targets else None))
            if session is not None:
                sections.append(
                    "已观察到的约定："
                    + (", ".join(session.conventions.observations[:4]) or "遵循附近代码风格")
                    + "。"
                )
        elif state.phase == AgentPhase.VALIDATING:
            if next_check is None:
                sections.append("已无剩余必做验证检查。")
            else:
                prepared = (getattr(agent, "current_validation_check", None),
                            getattr(agent, "current_validator_resolution", None))
                if prepared[0] is None or prepared[0].id != next_check.id:
                    # Rendering must not bind/rebind or mutate the ledger.
                    # The orchestration loop prepares this snapshot first.
                    prepared = (next_check, None)
                next_check, recommendation = prepared
                status = getattr(recommendation, "status", None)
                if recommendation and getattr(status, "value", status) == "resolved":
                    action = f"运行 {recommendation.tool_name}，参数 {recommendation.arguments!r}。"
                elif recommendation:
                    action = f"解析状态={getattr(status, 'value', status)}：{recommendation.reason}"
                else:
                    action = "只做足以解析该检查的探查；不要换成其他检查。"
                sections.append(
                    f"下一项必做检查 {next_check.id}：{next_check.reason}；"
                    f"契约={next_check.contract_type}；强度={next_check.strength.name}。{action}"
                )
        elif state.phase == AgentPhase.FIXING:
            evidence = ledger.latest_evidence
            details = getattr(evidence, "details", {}) or {}
            paths = tuple(details.get("failure_paths", ()))
            sections.append(
                f"失败检查：{getattr(evidence, 'check_id', '') or 'unbound'}；"
                f"失败路径：{', '.join(paths) if paths else '当前验证目标'}。"
                "先在局部恢复，再做大范围搜索。"
            )
        elif state.phase == AgentPhase.FINALIZING:
            if next_check is None:
                sections.append("已无剩余必做验证检查；仅依据已记录证据收尾。")
            else:
                resolution = getattr(agent, "current_validator_resolution", None)
                if getattr(getattr(agent, "current_validation_check", None), "id", None) != next_check.id:
                    resolution = None
                status = getattr(getattr(resolution, "status", ""), "value", getattr(resolution, "status", ""))
                if status == "resolved":
                    action = f"运行 {resolution.tool_name}，参数 {resolution.arguments!r}。"
                elif status == "target_unresolved":
                    action = (
                        f"探查一个相关路径（"
                        f"{', '.join(getattr(agent, 'validation_paths_for', lambda _: targets)(next_check)) or '无'}"
                        f"）并重新绑定同一检查。"
                    )
                else:
                    action = "创建确定性阻塞项；不要继续探查或编造其他验证器。"
                sections.append(
                    f"下一项必做检查 {next_check.id}：{next_check.reason}；"
                    f"契约={next_check.contract_type}；"
                    f"解析={status or 'unprepared'}：{getattr(resolution, 'reason', '')}。{action}"
                )
        if current_plan_step is not None and state.phase in {AgentPhase.ACTING, AgentPhase.FIXING}:
            sections.append(f"当前计划步骤：{current_plan_step.id}。{current_plan_step.description}")
        summary = agent.working_summary.render_relevant(targets, max_items=4)
        if summary:
            sections.append("近期相关事实：\n" + summary[-1200:])
        memory_store = getattr(agent, "long_term_memory_store", None)
        retrieved = getattr(agent, "_retrieved_long_term_memory", ())
        if memory_store is not None and retrieved:
            advisory = memory_store.render_retrieved(retrieved)
            if advisory:
                sections.append("参考性历史任务记忆：\n" + str(advisory)[:500])
        return "\n\n".join(sections).strip() + "\n"
