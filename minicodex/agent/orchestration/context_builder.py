"""Build phase-specific context from deterministic agent state."""

from __future__ import annotations

from ..editing import EditStrategyHint
from ..task_state import AgentPhase
from ...prompts.system import build_turn_context


class ContextBuilder:
    """Build small phase-specific context from current deterministic state."""

    def __init__(self, edit_strategy: EditStrategyHint | None = None) -> None:
        self.edit_strategy = edit_strategy or EditStrategyHint()

    def build(self, agent, *, current_plan_step, remaining_agent_steps: int) -> str:
        state = agent.task_progress_state(remaining_agent_steps)
        targets = tuple(state.relevant_paths or state.target_paths)
        target_text = ", ".join(targets) if targets else "not explicit"
        sections = [
            f"Task: {state.user_request or getattr(agent, 'active_user_request', '')}",
            f"Intent: {state.intent.value}. Mode: {state.mode.value if state.mode else 'unknown'}. Phase: {state.phase.value}.",
            f"Targets: {target_text}. Remaining steps: {remaining_agent_steps}.",
        ]
        requirements = getattr(agent, "task_requirements", None)
        if requirements is not None and requirements.items:
            sections.append(
                "Current task requirements:\n" + "\n".join(
                    f"- {item.id} [{'satisfied' if item.satisfied else 'open'}]: {item.description}"
                    for item in requirements.items[:12]
                )
            )
        summary = agent.working_summary.render_relevant(targets, max_items=8)

        if state.phase == AgentPhase.INSPECTING:
            sections.append("Inspect only the minimum target code needed to decide the next action.")
            repo_fragment = str(getattr(agent, "repo_map_text", "") or "")[:1800]
            if repo_fragment:
                sections.append("Repository map:\n" + repo_fragment)
        elif state.phase == AgentPhase.ACTING:
            target = targets[0] if targets else None
            sections.append(self.edit_strategy.render(agent.workspace, target))
            if current_plan_step is not None:
                sections.append(
                    f"Current plan step: {current_plan_step.id}. {current_plan_step.description}"
                )
        elif state.phase == AgentPhase.VALIDATING:
            registered = set(getattr(agent.registry, "_tools", {}) or {})
            selection = agent.validation_selector.select(
                target_paths=targets,
                registered_tools=registered,
                runtime_behavior=self._runtime_behavior_requested(agent),
                revision=state.edit_revision,
                desired_purpose=(
                    "acceptance" if not state.acceptance_passed else "regression"
                ),
            )
            recommendation = (
                f"Run {selection.tool_name}"
                + (f" on {selection.path}" if selection.path else "")
                + f" as {selection.purpose}."
                if selection
                else "Obtain the missing targeted validation evidence."
            )
            sections.append("Validation recommendation: " + recommendation)
        elif state.phase == AgentPhase.FIXING:
            evidence = getattr(agent.validation_pipeline.state, "latest_evidence", None)
            details = getattr(evidence, "details", {}) or {}
            failure_paths = tuple(details.get("failure_paths", ()))
            sections.append(
                "Latest failure paths: "
                + (", ".join(failure_paths) if failure_paths else "use the current validation target")
                + ". Recover locally before broad search or replanning."
            )
        elif state.phase == AgentPhase.FINALIZING:
            decision = agent.completion_policy.evaluate(agent)
            sections.append("Only the remaining completion requirement matters: " + decision.reason)

        if summary:
            sections.append("Recent relevant facts:\n" + summary[-2200:])
        retrieved = getattr(agent, "_retrieved_long_term_memory", ()) or ()
        store = getattr(agent, "long_term_memory_store", None)
        if retrieved and store is not None:
            try:
                memory_text = str(store.render_retrieved(retrieved) or "").strip()
            except Exception:
                memory_text = ""
            if memory_text:
                sections.append("Advisory prior-task memory:\n" + memory_text[-1800:])
        return "\n\n".join(sections).strip() + "\n"

    def build_detailed(
        self,
        agent,
        *,
        plan=None,
        current_step=None,
        remaining_agent_steps: int | None = None,
    ) -> str:
        """Build the detailed task context used by direct facade callers."""

        compact_context = bool(
            agent.execution_policy
            and agent.execution_policy.compact_context
        )
        if not compact_context:
            agent._refresh_repo_map()

        try:
            if compact_context:
                task_state = agent.git_awareness.task_state()
                touched = task_state.agent_touched_files
                git_awareness_text = (
                    "Agent-touched files: "
                    + (", ".join(touched) if touched else "none yet")
                )
            else:
                agent.git_awareness.refresh()
                git_awareness_text = agent.git_awareness.render()
        except Exception as exc:
            git_awareness_text = (
                "Git awareness unavailable: "
                f"{type(exc).__name__}: {exc}"
            )

        try:
            safety_policy_text = (
                "Use dedicated edit tools for file mutations. Unsafe "
                "destructive shell operations may be blocked."
                if compact_context
                else agent.safety_policy.render()
            )
        except Exception as exc:
            safety_policy_text = (
                "Safety policy unavailable: "
                f"{type(exc).__name__}: {exc}"
            )

        plan_text = agent._plan_to_text(plan) if plan else "No explicit plan."
        current_step_text = (
            f"{current_step.id}. {current_step.description}"
            if current_step
            else "No active plan step."
        )

        if compact_context:
            validation = agent.validation_pipeline.state
            state = agent.task_progress_state(remaining_agent_steps)
            registered = set(getattr(agent.registry, "_tools", {}) or {})
            targets = tuple(
                getattr(agent.execution_route, "target_paths", ()) or ()
            )
            selection = agent.validation_selector.select(
                target_paths=targets,
                registered_tools=registered,
                runtime_behavior=self._runtime_behavior_requested(agent),
                revision=validation.edit_revision,
                desired_purpose=(
                    "acceptance"
                    if not validation.acceptance_passed
                    else "regression"
                ),
            )
            action_text = (
                agent.action_controller.INSTRUCTION
                if agent.action_controller.action_required
                else "Inspect minimally, then edit or validate."
            )
            return "\n\n".join(
                [
                    f"User request: {agent.active_user_request or ''}",
                    f"Execution mode: FAST. Phase: {state.phase.value}. "
                    f"Planning active: {agent.active_plan is not None}.",
                    "Target paths: "
                    + (", ".join(targets) if targets else "not explicit"),
                    f"Remaining agent steps: {remaining_agent_steps}",
                    (
                        "Validation state: "
                        f"revision={validation.edit_revision}, "
                        f"has_edit={validation.has_edit}, "
                        f"acceptance_passed={validation.acceptance_passed}."
                    ),
                    agent.working_summary.render_relevant(
                        targets,
                        max_items=8,
                    )[-2000:],
                    (
                        f"Recommended acceptance validator: {selection.tool_name}"
                        + (
                            f" for {selection.path}"
                            if selection and selection.path
                            else ""
                        )
                        if selection
                        else "No dedicated acceptance validator selected."
                    ),
                    action_text,
                    safety_policy_text,
                ]
            ).strip() + "\n"

        return build_turn_context(
            task_state_text=(
                "Task state: "
                f"mode={agent.task_state.mode.value if agent.task_state.mode else 'unknown'}, "
                f"phase={agent.task_state.phase.value}, "
                f"edit_revision={agent.task_state.edit_revision}, "
                f"validation_revision={agent.task_state.validation_revision}."
            ),
            plan_text=plan_text,
            current_step_text=current_step_text,
            remaining_agent_steps=remaining_agent_steps,
            working_summary_text=agent.working_summary.render_relevant(
                tuple(getattr(agent.execution_route, "target_paths", ()) or ()),
                max_items=14,
            ),
            repo_map_text=(
                agent.repo_map_text[:2000]
                if compact_context
                else agent.repo_map_text
            ),
            git_awareness_text=git_awareness_text,
            safety_policy_text=safety_policy_text,
        )

    @staticmethod
    def _runtime_behavior_requested(agent) -> bool:
        text = str(getattr(agent, "active_user_request", "") or "").casefold()
        return any(marker in text for marker in (
            "game", "playable", "click", "keypress", "keyboard", "interaction",
            "游戏", "可玩", "点击", "键盘", "交互",
        ))
