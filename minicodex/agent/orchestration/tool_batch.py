"""Focused deterministic helpers for shared-loop tool batches."""

from __future__ import annotations

from dataclasses import dataclass, field

from .message_protocol import close_tool_batch_before_control_transition
from ..reason_codes import ReasonCode


@dataclass(frozen=True)
class ToolRestriction:
    failure_type: str
    reason: str
    data: dict = field(default_factory=dict)
    reason_code: ReasonCode | None = None


def resolve_tool_restriction(agent, tool_name: str, arguments: dict) -> ToolRestriction | None:
    """Apply edit recovery, finalization, action, and dependency policy in order."""

    from ..progress.executable_tool_policy import (
        VALIDATION_MILESTONE_MESSAGE,
        CAP_CODE_EDIT,
    )

    unit = getattr(getattr(agent, "task_state", None), "work_unit", None)
    registry = getattr(agent, "registry", None)
    caps = registry.capabilities_for(tool_name) if registry and tool_name in getattr(registry, "_tools", {}) else frozenset()
    milestone_due = bool(
        unit and not unit.closed and unit.milestone_due and CAP_CODE_EDIT in caps
    )
    if milestone_due:
        return ToolRestriction("validation_milestone", VALIDATION_MILESTONE_MESSAGE)

    retry = getattr(agent, "edit_retry", None)
    edit_retry_needs_read = False
    edit_retry_path = ""
    if retry is not None:
        pending = getattr(retry, "pending", None)
        if pending is not None and not bool(getattr(pending, "read_completed", False)):
            failure = getattr(pending, "failure_type", None)
            failure_value = getattr(failure, "value", failure)
            if str(failure_value or "") != "symbol_not_found":
                edit_retry_needs_read = True
                edit_retry_path = str(getattr(pending, "path", "") or "")
        reason = retry.restriction_reason(tool_name, arguments)
        if reason:
            return ToolRestriction("edit_retry_restriction", reason)

    finalization = getattr(agent, "finalization", None)
    if finalization is not None:
        reason = finalization.restriction_reason(tool_name)
        if reason:
            return ToolRestriction("finalization_restriction", reason)

    action = getattr(agent, "action_controller", None)
    policy = getattr(agent, "execution_policy", None)
    if action is not None and policy is not None:
        fin = getattr(agent, "finalization", None)
        reason = action.restriction_reason(
            tool_name,
            arguments,
            policy,
            finalization_active=bool(getattr(fin, "active", False)),
            allow_proof_inspection=bool(getattr(fin, "allow_proof_inspection", False)),
            milestone_due=bool(
                unit and not unit.closed and bool(getattr(unit, "milestone_due", False))
            ),
            edit_retry_needs_read=edit_retry_needs_read,
            edit_retry_path=edit_retry_path,
        )
        if reason:
            return ToolRestriction("action_required_restriction", reason, reason_code=ReasonCode.INSPECTION_LIMIT)

    if tool_name == "install_python_package" and hasattr(agent, "dependency_resolver"):
        route = getattr(agent, "execution_route", None)
        resolution = agent.dependency_resolver.resolve(
            str(arguments.get("package", "")),
            target_paths=tuple(getattr(route, "target_paths", ()) or ()),
        )
        agent.latest_dependency_resolution = resolution
        if not resolution.install_allowed:
            return ToolRestriction(
                "dependency_manifest_required",
                resolution.reason,
                {
                    "package": resolution.package,
                    "manifests": resolution.manifests,
                    "preferred_manifest": resolution.preferred_manifest,
                    "recommended_action": resolution.action,
                },
                ReasonCode.DEPENDENCY_MANIFEST_REQUIRED,
            )
    return None


def commit_batch_transition(
    messages: list,
    remaining_tool_calls: list,
    *,
    reason: str,
    followup: str | None = None,
) -> None:
    """Close skipped calls before committing one provider-history transition."""

    close_tool_batch_before_control_transition(
        messages,
        remaining_tool_calls,
        reason,
        followup_user_message=followup,
    )
