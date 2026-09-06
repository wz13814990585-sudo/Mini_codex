"""Safety policy boundary around tool execution."""

from __future__ import annotations

from .safety import (
    SafetyDecision,
)
from .tool_executor import (
    PreparedToolCall,
    ToolExecution,
)

from ..tools.results import (
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
    ):

        self.executor = (
            executor
        )

        self.policy = (
            policy
        )

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

            decision = (
                self.policy
                .assess(
                    tool_name=(
                        prepared.tool_name
                    ),
                    arguments=(
                        prepared.arguments
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