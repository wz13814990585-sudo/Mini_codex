"""Safety policy boundary around tool execution."""

from __future__ import annotations

from .safety import (
    SafetyDecision,
)
from ..runtime.tool_types import (
    PreparedToolCall,
    ToolExecution,
)
from ..reason_codes import ReasonCode

from ...tools.results import (
    ToolResult,
)


class SafetyToolExecutor:
    """
    Deterministic safety wrapper.

    Execution order:

        prepare
            ↓
        safety policy
            ↓
        BLOCKED
            → return ToolResult without execution

        SAFE / CAUTION
            ↓
        downstream executor
            ↓
        annotate result with safety metadata
    """

    def __init__(
        self,
        *,
        executor,
        policy,
        intervention_hook=None,
        registry=None,
    ):

        self.executor = (
            executor
        )

        self.policy = (
            policy
        )
        # The host may request approval or clarification. A hook never silently
        # overrides a safety denial; an approved task must be explicitly retried.
        self.intervention_hook = intervention_hook
        self.registry = registry

    # =========================================================
    # Prepare
    # =========================================================

    def prepare(
        self,
        tool_name: str,
        raw_arguments: str,
    ) -> PreparedToolCall:

        return (
            self.executor
            .prepare(
                tool_name=tool_name,
                raw_arguments=raw_arguments,
            )
        )

    # =========================================================
    # Execute
    # =========================================================

    def execute_prepared(
        self,
        prepared: PreparedToolCall,
    ) -> ToolExecution:

        # =====================================================
        # Preparation Already Failed
        # =====================================================

        if (
            prepared.error
            is not None
        ):

            return (
                self.executor
                .execute_prepared(
                    prepared
                )
            )

        # =====================================================
        # Safety Decision
        # =====================================================

        try:

            assessment_name = prepared.tool_name
            assessment_arguments = prepared.arguments
            if self.registry is not None and prepared.tool_name in getattr(self.registry, "_tools", {}):
                caps = self.registry.capabilities_for(prepared.tool_name)
                if "code.edit" in caps and prepared.tool_name not in self.policy.EDIT_TOOL_NAMES:
                    assessment_name = "patch_file"
                elif "process.run" in caps:
                    assessment_name = "run_command"
                elif "service.validate" in caps:
                    import shlex
                    assessment_name = "run_command"
                    assessment_arguments = {"command": shlex.join(prepared.arguments.get("argv", []))}

            decision = (
                self.policy
                .assess(
                    tool_name=(
                        assessment_name
                    ),
                    arguments=(
                        assessment_arguments
                    ),
                )
            )

        except Exception as e:

            # Safety policy failure must fail CLOSED.
            return ToolExecution(
                tool_name=(
                    prepared.tool_name
                ),
                arguments=(
                    prepared.arguments
                ),
                result=ToolResult(
                    success=False,
                    summary=(
                        "Tool execution was blocked "
                        "because the safety policy "
                        "could not produce a reliable "
                        "decision."
                    ),
                    data={
                        "tool_name": (
                            prepared.tool_name
                        ),
                        "failure_type": (
                            "safety_policy_failure"
                        ),
                        "reason_code": ReasonCode.UNSAFE_COMMAND.value,
                        "safety": {
                            "level": (
                                "blocked"
                            ),
                            "allowed": (
                                False
                            ),
                            "rule": (
                                "policy_exception"
                            ),
                        },
                    },
                    error=(
                        f"{type(e).__name__}: "
                        f"{e}"
                    ),
                ),
            )

        # =====================================================
        # BLOCKED
        # =====================================================

        if not (
            decision.allowed
        ):
            if self.intervention_hook is not None:
                self.intervention_hook(decision.intervention, decision, prepared)

            return (
                self._blocked_execution(
                    prepared=prepared,
                    decision=decision,
                )
            )

        # =====================================================
        # SAFE / CAUTION
        # =====================================================

        execution = (
            self.executor
            .execute_prepared(
                prepared
            )
        )

        result = (
            execution.result
        )

        # =====================================================
        # Preserve Safety Metadata
        # =====================================================

        result.data[
            "safety"
        ] = (
            decision
            .to_dict()
        )

        if (
            decision
            .requires_attention
        ):

            result.data[
                "safety_warning"
            ] = (
                decision.reason
            )

        return execution

    # =========================================================
    # Blocked Result
    # =========================================================

    @staticmethod
    def _blocked_execution(
        *,
        prepared: PreparedToolCall,
        decision: SafetyDecision,
    ) -> ToolExecution:

        return ToolExecution(
            tool_name=(
                prepared.tool_name
            ),
            arguments=(
                prepared.arguments
            ),
            result=ToolResult(
                success=False,
                summary=(
                    f"Tool '{prepared.tool_name}' "
                    "was blocked by the "
                    "Harness safety policy."
                ),
                data={
                    "tool_name": (
                        prepared.tool_name
                    ),
                    "failure_type": (
                        "safety_blocked"
                    ),
                    "reason_code": ReasonCode.UNSAFE_COMMAND.value,
                    "safety": (
                        decision
                        .to_dict()
                    ),
                },
                error=(
                    decision.reason
                ),
                llm_content=(
                    "Safety decision:\n"
                    f"Level: "
                    f"{decision.level.value}\n"
                    f"Rule: "
                    f"{decision.rule}\n"
                    f"Reason: "
                    f"{decision.reason}"
                ),
            ),
        )
