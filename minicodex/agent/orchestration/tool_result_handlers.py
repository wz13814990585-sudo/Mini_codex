"""Domain reactions to completed edits and validations, separate from batch protocol."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..editing.edit_verifier import EditVerifier
from ..progress import ProgressKind, ProgressSignal
from ..task_state import RuntimeEventType
from ..validation.plan import RequirementEvidenceResolver


class EditResultHandler:
    def apply(self, agent, *, tool_name, arguments, result, current_plan_step, emit):
        revision = agent.validation_pipeline.record_edit()
        requirements = getattr(agent, "task_requirements", None)
        if requirements is not None:
            requirements.invalidate_revision(revision)
            agent.sync_requirements_state()
        agent.working_summary.advance_revision(revision)
        agent._repo_map_initialized = False
        agent._repo_map_revision = None
        path = str(arguments.get("path", ""))
        agent.workspace_session.invalidate(path)
        memory = getattr(getattr(agent, "working_summary", None), "memory", None)
        if memory is not None:
            try:
                memory.invalidate_path(path)
            except Exception:
                pass
        emit(agent, RuntimeEventType.EDIT_APPLIED,
             edit_revision=revision, path=path,
             milestone_check_ids=tuple(check.id for check in agent.validation_pipeline.state.plan.checks
                                      if check.required and check.milestone == "work_unit"),
             diff_quality_issues=result.data.get("diff_quality_issues", ()))
        if hasattr(agent, "step_evidence"):
            agent.step_evidence.record(step_id=current_plan_step.id if current_plan_step else None,
                                       edit_revision=revision, tool_name=tool_name,
                                       arguments=arguments, result=result)
        agent.progress.mark_meaningful_progress()
        _, completed = agent.plan_orchestrator.reconcile(agent)
        return ProgressSignal(ProgressKind.ADVANCED, f"Edit created revision {revision}."), completed


@dataclass(frozen=True)
class ValidationHandled:
    evidence: object | None
    signal: ProgressSignal
    decision: object | None
    completed_plan: bool


class ValidationResultHandler:
    def apply(self, agent, *, tool_name, arguments, result, capabilities, metrics, emit):
        if "test.run" in capabilities:
            target = str(arguments.get("path", "")).split("::", 1)[0]
            if any(checkpoint.sealed and not checkpoint.rolled_back and checkpoint.snapshot.path == target
                   for checkpoint in agent.checkpoint_manager.all_checkpoints()):
                result.data["agent_test_only"] = True
        unit = getattr(agent.task_state, "work_unit", None)
        if unit and not unit.closed:
            syntax_errors = []
            for path in unit.edited_paths:
                file = Path(agent.workspace) / path
                if file.suffix == ".py" and file.is_file():
                    try:
                        EditVerifier.validate_candidate(file, file.read_text(encoding="utf-8"))
                    except (ValueError, OSError, UnicodeError) as exc:
                        syntax_errors.append(f"{path}: {exc}")
            if syntax_errors:
                result.data.update(outcome="failed", tests_passed=False, command_succeeded=False,
                                   failed=len(syntax_errors), failed_tests=syntax_errors,
                                   milestone_syntax_errors=syntax_errors)
                if capabilities & {"validation.static_web", "validation.browser", "service.validate"}:
                    result.data["errors"] = [*result.data.get("errors", []), *syntax_errors]
        evidence = agent.validation_pipeline.observe(tool_name=tool_name, arguments=arguments, result=result,
                                                     capabilities=capabilities)
        if evidence is None:
            return ValidationHandled(None, ProgressSignal(ProgressKind.NONE, "No validation evidence was produced."), None, False)
        checks = agent.validation_pipeline.state.plan.checks
        contract = next((check for check in checks if check.id == evidence.check_id), None)
        if metrics is not None and checks and evidence.purpose.value == "acceptance" and (
            contract is None or (contract.target and contract.target != evidence.target)
        ):
            metrics.wrong_validation_target_count += 1
        requirements = getattr(agent, "task_requirements", None)
        if requirements is not None:
            RequirementEvidenceResolver().resolve(requirements, agent.validation_pipeline.state)
            agent.sync_requirements_state()
        ledger = agent.validation_pipeline.state
        milestones = (all(ledger.proof(check_id) is not None for check_id in unit.milestone_check_ids)
                      if unit and evidence.check_id in unit.milestone_check_ids else None)
        emit(agent, RuntimeEventType.VALIDATION_OBSERVED,
             outcome=evidence.outcome, validation_revision=ledger.evidence_sequence,
             acceptance_passed=ledger.acceptance_passed, relevant_validation_passed=ledger.targeted_passed,
             full_validation_passed=ledger.full_passed, evidence_edit_revision=evidence.edit_revision,
             validation_check=evidence.check_id, requirement_ids=evidence.requirement_ids,
             capabilities=tuple(sorted(capabilities)), workunit_id=unit.id if unit else None,
             workunit_all_milestones_resolved=milestones)
        _, completed = agent.plan_orchestrator.reconcile(agent)
        decision = agent.validation_orchestrator.apply(agent=agent, evidence=evidence)
        if evidence.outcome.value == "passed" and agent.task_state.recovery_level > 0 and metrics is not None:
            metrics.recovery_successes += 1
        signal = agent.latest_progress_signal or ProgressSignal(ProgressKind.NONE, "Validation did not yield comparable progress.")
        return ValidationHandled(evidence, signal, decision, completed)
