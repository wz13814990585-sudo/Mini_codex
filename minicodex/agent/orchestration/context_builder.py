"""Build phase-specific context from deterministic task facts."""

from __future__ import annotations

from ..editing import EditStrategyHint
from ..task_state import AgentPhase


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
            f"Task: {state.user_request or getattr(agent, 'active_user_request', '')}",
            f"Phase: {state.phase.value}; targets: {', '.join(targets) or 'not explicit'}; remaining steps: {remaining_agent_steps}.",
            "Authority: current workspace/tool evidence > explicit request > runtime projection > memory > assumptions.",
        ]
        unit = state.work_unit
        if unit and not unit.closed:
            sections.append(f"WorkUnit {unit.id}: paths={unit.edited_paths}; edits={unit.edits}/{unit.max_edits}; "
                            f"milestones={', '.join(unit.milestone_check_ids) or 'pending resolution'}.")
        session = getattr(agent, "workspace_session", None)
        if state.phase == AgentPhase.INSPECTING:
            sections.append("Locate → expand → read only the smallest relevant code before acting.")
            repo_fragment = str(getattr(agent, "repo_map_text", "") or "")[:1800]
            if repo_fragment:
                sections.append("Repository map:\n" + repo_fragment)
        elif state.phase == AgentPhase.ACTING:
            sections.append(self.edit_strategy.render(agent.workspace, targets[0] if targets else None))
            if session is not None:
                sections.append("Observed conventions: " + (", ".join(session.conventions.observations[:4]) or "follow nearby code") + ".")
        elif state.phase == AgentPhase.VALIDATING:
            if next_check is None:
                sections.append("No required validation check remains.")
            else:
                resolver = getattr(agent, "validator_resolver", None)
                recommendation = resolver.resolve(
                    next_check, registry=agent.registry,
                    profile=session.profile if session else None, paths=targets,
                    revision=session.revision if session else state.edit_revision,
                ) if resolver else None
                action = (f"Run {recommendation.tool_name} with {recommendation.arguments!r}."
                          if recommendation else "Inspect only enough to resolve this exact check; do not substitute another one.")
                sections.append(f"Next required check {next_check.id}: {next_check.observable or next_check.reason}; "
                                f"strength={next_check.strength.name}; capability={next_check.capability}. {action}")
        elif state.phase == AgentPhase.FIXING:
            evidence = ledger.latest_evidence
            details = getattr(evidence, "details", {}) or {}
            paths = tuple(details.get("failure_paths", ()))
            sections.append(f"Failing check: {getattr(evidence, 'check_id', '') or 'unbound'}; "
                            f"failure paths: {', '.join(paths) if paths else 'current validation target'}. "
                            "Recover locally before broad search.")
        elif state.phase == AgentPhase.FINALIZING:
            sections.append("Remaining required checks: " + (", ".join(check.id for check in missing) or "none") + ".")
        if current_plan_step is not None and state.phase in {AgentPhase.ACTING, AgentPhase.FIXING}:
            sections.append(f"Current plan outcome: {current_plan_step.id}. {current_plan_step.description}")
        summary = agent.working_summary.render_relevant(targets, max_items=4)
        if summary:
            sections.append("Recent relevant facts:\n" + summary[-1200:])
        memory_store = getattr(agent, "long_term_memory_store", None)
        retrieved = getattr(agent, "_retrieved_long_term_memory", ())
        if memory_store is not None and retrieved:
            advisory = memory_store.render_retrieved(retrieved)
            if advisory:
                sections.append("Advisory prior-task memory:\n" + str(advisory)[:500])
        return "\n\n".join(sections).strip() + "\n"
