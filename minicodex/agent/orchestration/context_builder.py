"""Build phase-specific context from deterministic agent state."""

from __future__ import annotations

from ..editing import EditStrategyHint
from ..task_state import AgentPhase
from ..validation.ladder import VerificationLadder


class ContextBuilder:
    """Build small phase-specific context from current deterministic state."""

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
        target_text = ", ".join(targets) if targets else "not explicit"
        sections = [
            f"Task: {state.user_request or getattr(agent, 'active_user_request', '')}",
            f"Intent: {state.intent.value}. Mode: {state.mode.value if state.mode else 'unknown'}. Phase: {state.phase.value}.",
            f"Targets: {target_text}. Remaining steps: {remaining_agent_steps}.",
            (
                "Current evidence: "
                f"edit_revision={state.edit_revision}; "
                f"acceptance={state.acceptance_passed}; "
                f"relevant_regression={state.relevant_validation_passed}; "
                f"full_regression={state.full_validation_passed}."
            ),
            (
                "Authority: current workspace/tool evidence > explicit request > "
                "current runtime state > current validation > memory > assumptions."
            ),
        ]
        requirements = getattr(agent, "task_requirements", None)
        if state.work_unit and not state.work_unit.closed:
            unit = state.work_unit
            sections.append(f"WorkUnit {unit.id}: {unit.edited_paths}; edits={unit.edits}/{unit.max_edits}. "
                            "Finish cohesive related edits, then validate the milestone.")
        session = getattr(agent, "workspace_session", None)
        if session is not None:
            sections.append(session.render(targets))
            sections.append("Verification ladder: " + "; ".join(
                f"{r.strength.name}: {r.command or r.reason}"
                for r in VerificationLadder().select(session.profile, targets, state.user_request)))
        ledger = agent.validation_pipeline.state
        if ledger.plan.checks:
            sections.append("Verification contracts (supply validation_check on each validation call):\n" + "\n".join(
                f"- {c.id} -> {','.join(c.requirement_ids)}: {c.reason}; "
                f"target={c.target or 'choose a specific observable assertion'}; "
                f"{'proven' if ledger.proof(c.id) else 'missing current proof'}"
                for c in ledger.plan.checks))
        if requirements is not None and requirements.items:
            sections.append(
                "Current task requirements:\n" + "\n".join(
                    f"- {item.id} [{'satisfied' if item.satisfied else 'open'}]: {item.description}"
                    for item in requirements.items[:12]
                )
            )
        if current_plan_step is not None:
            criteria = tuple(getattr(current_plan_step, "acceptance_criteria", ()) or ())
            expected = tuple(getattr(current_plan_step, "expected_targets", ()) or ())
            sections.append(
                "Current plan outcome: "
                f"{current_plan_step.id}. {current_plan_step.description}\n"
                f"Expected targets: {', '.join(expected) if expected else 'not specified'}\n"
                f"Acceptance criteria: {criteria if criteria else 'semantic/current validation'}"
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
        elif state.phase == AgentPhase.VALIDATING:
            acceptance_missing = any(c.required and c.purpose.value == "acceptance" and not ledger.proof(c.id)
                                     for c in ledger.plan.checks) if ledger.plan.checks else not state.acceptance_passed
            registered = set(getattr(agent.registry, "_tools", {}) or {})
            selection = agent.validation_selector.select(
                target_paths=targets,
                registered_tools=registered,
                runtime_behavior=self._runtime_behavior_requested(agent),
                revision=session.revision if session is not None else state.edit_revision,
                desired_purpose=(
                    "acceptance" if acceptance_missing else "regression"
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

    @staticmethod
    def _runtime_behavior_requested(agent) -> bool:
        text = str(getattr(agent, "active_user_request", "") or "").casefold()
        return any(marker in text for marker in (
            "game", "playable", "click", "keypress", "keyboard", "interaction",
            "游戏", "可玩", "点击", "键盘", "交互",
        ))
