"""Focused deterministic helpers for shared-loop tool batches."""

from __future__ import annotations

from dataclasses import dataclass, field

from .message_protocol import close_tool_batch_before_control_transition


@dataclass(frozen=True)
class ToolRestriction:
    failure_type: str
    reason: str
    data: dict = field(default_factory=dict)


def resolve_tool_restriction(agent, tool_name: str, arguments: dict) -> ToolRestriction | None:
    """Apply edit recovery, finalization, action, and dependency policy in order."""

    retry = getattr(agent, "edit_retry", None)
    if retry is not None:
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
        reason = action.restriction_reason(tool_name, arguments, policy)
        if reason:
            return ToolRestriction("action_required_restriction", reason)

    if tool_name == "install_python_package" and hasattr(agent, "dependency_resolver"):
        route = getattr(agent, "execution_route", None)
        resolution = agent.dependency_resolver.resolve(
            str(arguments.get("package", "")),
            target_paths=tuple(getattr(route, "target_paths", ()) or ()),
        )
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
