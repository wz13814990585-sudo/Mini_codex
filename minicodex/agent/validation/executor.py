"""Harness-owned deterministic validation execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..observability.trace import TraceEventType
from .evidence import ValidationOutcome
from .validator_resolver import ResolutionStatus, ValidatorResolution


class ValidationExecutionState(str, Enum):
    PROVEN = "proven"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    BLOCKED = "blocked"
    UNRESOLVED = "unresolved"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class ValidationExecutionResult:
    state: ValidationExecutionState
    check_id: str
    resolution: ValidatorResolution
    evidence: object | None = None
    tool_result: object | None = None
    reason: str = ""


@dataclass(frozen=True)
class _PreparedValidationCall:
    tool_name: str
    arguments: dict
    error: object | None = None


class ValidationExecutor:
    """Resolve externally, execute internally, and bind proof without an LLM turn."""

    def execute(self, agent, check, resolution: ValidatorResolution) -> ValidationExecutionResult:
        ledger = agent.validation_pipeline.state
        existing = ledger.proof(check.id)
        if existing is not None:
            return ValidationExecutionResult(
                ValidationExecutionState.SKIPPED, check.id, resolution,
                existing, reason="current_revision_already_proven",
            )
        prior_evidence = next((
            item for item in reversed(ledger.evidence_history)
            if item.edit_revision == ledger.edit_revision and item.check_id == check.id
        ), None)
        if (
            prior_evidence is not None
            and prior_evidence.outcome == ValidationOutcome.INCONCLUSIVE
        ):
            attempts = sum(
                item.edit_revision == ledger.edit_revision and item.check_id == check.id
                and item.outcome == ValidationOutcome.INCONCLUSIVE
                for item in ledger.evidence_history
            )
            if attempts >= 2:
                ledger.mark_blocked(check.id, "验证器连续两次执行仍无定论。")
                return ValidationExecutionResult(
                    ValidationExecutionState.BLOCKED, check.id, resolution,
                    prior_evidence, reason="验证器连续两次执行仍无定论。",
                )
        elif prior_evidence is not None:
            return ValidationExecutionResult(
                ValidationExecutionState.SKIPPED, check.id, resolution,
                prior_evidence, reason="awaiting_repair_or_fresh_revision",
            )
        if resolution.status != ResolutionStatus.RESOLVED:
            state = (
                ValidationExecutionState.BLOCKED
                if resolution.status in {ResolutionStatus.CAPABILITY_MISSING, ResolutionStatus.UNSUPPORTED}
                else ValidationExecutionState.UNRESOLVED
            )
            prior_unresolved = sum(
                item.get("edit_revision") == ledger.edit_revision
                and item.get("check_id") == check.id
                and item.get("execution_status") == "target_unresolved"
                for item in ledger.execution_observations
            )
            if state == ValidationExecutionState.UNRESOLVED and prior_unresolved >= 1:
                state = ValidationExecutionState.BLOCKED
            ledger.observe_execution(
                check_id=check.id,
                execution_status=(
                    "target_unresolved"
                    if state == ValidationExecutionState.UNRESOLVED
                    else "blocked"
                ),
                reason=resolution.reason,
                proof_accepted=False,
            )
            if state == ValidationExecutionState.BLOCKED:
                ledger.mark_blocked(check.id, resolution.reason)
            return ValidationExecutionResult(state, check.id, resolution, reason=resolution.reason)

        backend_arguments = {
            key: value for key, value in resolution.arguments.items()
            if key != "validation_check"
        }
        execution = agent.tool_executor.execute_prepared(
            _PreparedValidationCall(resolution.tool_name, backend_arguments)
        )
        result = execution.result
        capabilities = agent.registry.capabilities_for(resolution.tool_name)
        metrics = getattr(agent, "execution_metrics", None)
        if metrics is not None:
            metrics.record_tool(
                resolution.tool_name,
                llm_call_count=agent.token_metrics.call_count,
                arguments=resolution.arguments,
                success=result.success,
                revision=ledger.edit_revision,
                capabilities=capabilities,
            )

        previous_revision = ledger.edit_revision
        refresh = getattr(agent, "refresh_workspace_facts", None)
        if callable(refresh):
            refresh()
        if ledger.edit_revision != previous_revision:
            result.data["workspace_changed_during_validation"] = True

        evidence = agent.validation_pipeline.observe(
            resolution.tool_name,
            resolution.arguments,
            result,
            capabilities,
            resolution=resolution,
        )
        if evidence is None:
            failed_attempts = sum(
                item.get("edit_revision") == ledger.edit_revision
                and item.get("check_id") == check.id
                and item.get("execution_status") in {"crashed", "timeout", "unavailable"}
                for item in ledger.execution_observations
            )
            exhausted = failed_attempts >= 2
            if exhausted:
                ledger.mark_blocked(check.id, result.error or result.summary)
            self._emit(agent, check, resolution, result, None, proof_accepted=False)
            return ValidationExecutionResult(
                (ValidationExecutionState.BLOCKED if exhausted
                 else ValidationExecutionState.INCONCLUSIVE),
                check.id, resolution,
                tool_result=result, reason=result.error or result.summary,
            )

        proof = ledger.proof(check.id)
        self._emit(agent, check, resolution, result, evidence, proof_accepted=proof is not None)
        if evidence.outcome == ValidationOutcome.FAILED:
            state = ValidationExecutionState.FAILED
        elif evidence.outcome == ValidationOutcome.PASSED and proof is not None:
            state = ValidationExecutionState.PROVEN
        else:
            state = ValidationExecutionState.INCONCLUSIVE
        return ValidationExecutionResult(
            state, check.id, resolution, evidence, result, evidence.summary
        )

    @staticmethod
    def _emit(agent, check, resolution, result, evidence, *, proof_accepted: bool) -> None:
        data = {
            "check_id": check.id,
            "check_ids": [check.id],
            "requirement_ids": list(check.requirement_ids),
            "edit_revision": agent.validation_pipeline.state.edit_revision,
            "tool_name": resolution.tool_name,
            "execution_status": (
                getattr(getattr(evidence, "execution_status", None), "value", None)
                or ("executed" if result.success else "crashed")
            ),
            "purpose": check.purpose.value,
            "scope": getattr(getattr(evidence, "scope", None), "value", "targeted"),
            "capability": resolution.capability,
            "target": resolution.target,
            "contract_type": check.contract_type,
            "validation_key": resolution.validation_key,
            "evidence_strength": int(check.strength),
            "outcome": getattr(getattr(evidence, "outcome", None), "value", "inconclusive"),
            "proof_accepted": proof_accepted,
            "failure_reason": result.error or ("" if proof_accepted else result.summary),
        }
        recorder = getattr(agent, "trace_recorder", None)
        if recorder is not None:
            recorder.emit(
                TraceEventType.VALIDATION_EVIDENCE if evidence is not None
                else TraceEventType.VALIDATION_SKIPPED,
                data,
            )
        emit = getattr(agent, "apply_runtime_event", None)
        if not callable(emit):
            return
        from ..task_state import RuntimeEventType
        ledger = agent.validation_pipeline.state
        emit(
            RuntimeEventType.VALIDATION_OBSERVED,
            check_id=check.id,
            check_ids=(check.id,),
            requirement_ids=check.requirement_ids,
            edit_revision=ledger.edit_revision,
            evidence_edit_revision=getattr(evidence, "edit_revision", ledger.edit_revision),
            validation_revision=ledger.evidence_sequence,
            tool_name=resolution.tool_name,
            execution_status=data["execution_status"],
            purpose=check.purpose.value,
            scope=getattr(getattr(evidence, "scope", None), "value", "targeted"),
            capability=resolution.capability,
            target=resolution.target,
            contract_type=check.contract_type,
            validation_key=resolution.validation_key,
            evidence_strength=int(check.strength),
            outcome=getattr(evidence, "outcome", ValidationOutcome.INCONCLUSIVE),
            proof_accepted=proof_accepted,
            failure_reason=result.error or ("" if proof_accepted else result.summary),
            acceptance_passed=ledger.acceptance_passed,
            relevant_validation_passed=ledger.targeted_passed,
            full_validation_passed=ledger.full_passed,
        )
