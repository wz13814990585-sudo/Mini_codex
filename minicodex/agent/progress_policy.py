"""Deterministic no-progress and recovery policy."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import json


@dataclass(frozen=True)
class ProgressDecision:
    meaningful: bool
    stuck: bool
    no_progress_count: int
    repeated_observation: bool = False
    reason: str | None = None


class NoProgressPolicy:
    """Bound tool activity that does not change task state.

    This addresses the failure where one large edit already
    implements the feature, but successful read/search/git calls
    keep the same plan step alive until the global budget expires.
    Inspection success is evidence, not by itself a state transition.
    """

    INSPECTION_TOOLS = {
        "read_file",
        "search_code",
        "search_symbol",
        "list_files",
        "git_status",
        "git_diff",
    }

    EDIT_TOOLS = {
        "patch_file",
        "replace_lines",
        "replace_symbol",
        "write_file",
    }

    VALIDATION_TOOLS = {
        "run_tests",
        "validate_static_web",
    }

    RECOVERY_ALLOWED_TOOLS = (
        EDIT_TOOLS
        | VALIDATION_TOOLS
        | {
            "complete_plan_step",
            "replan",
            "install_python_package",
        }
    )

    RECOVERY_INSTRUCTION = (
        "Deterministic no-progress recovery is active. Do not "
        "continue free-form reconnaissance. Your next decision "
        "must be exactly one of: (A) validate the current "
        "implementation, (B) complete the current plan step if "
        "its criteria are satisfied, (C) make a concrete edit, "
        "(D) replan with a specific reason, or (E) stop with an "
        "explicit blocker."
    )

    def __init__(
        self,
        max_no_progress_steps: int = 5,
    ):
        self.max_no_progress_steps = max(
            1,
            int(max_no_progress_steps),
        )
        self.reset()

    def reset(self) -> None:
        self.current_step_id: int | None = None
        self.no_progress_count = 0
        self.recovery_active = False
        self.last_reason: str | None = None
        self._observations: dict[str, str] = {}
        self._validation_fingerprint: str | None = None

    def start_step(
        self,
        step_id: int | None,
    ) -> None:
        if step_id == self.current_step_id:
            return

        self.current_step_id = step_id
        self.no_progress_count = 0
        self.recovery_active = False
        self.last_reason = None
        self._observations.clear()
        self._validation_fingerprint = None

    def mark_progress(
        self,
        reason: str,
    ) -> None:
        self.no_progress_count = 0
        self.recovery_active = False
        self.last_reason = str(reason)
        self._observations.clear()

    def observe_tool_result(
        self,
        *,
        tool_name: str,
        arguments: dict,
        result,
        step_id: int | None,
        context_critical: bool = False,
    ) -> ProgressDecision:
        self.start_step(step_id)

        if self._tool_made_progress(
            tool_name,
            result,
        ):
            self.mark_progress(
                f"{tool_name} changed task state"
            )
            return ProgressDecision(
                meaningful=True,
                stuck=False,
                no_progress_count=0,
            )

        if tool_name in self.VALIDATION_TOOLS or (
            tool_name == "run_command"
            and str(
                arguments.get("purpose", "diagnostic")
            ).strip().lower()
            == "acceptance"
        ):
            fingerprint = self._result_fingerprint(
                tool_name,
                arguments,
                result,
            )
            changed = (
                fingerprint
                != self._validation_fingerprint
            )
            self._validation_fingerprint = fingerprint

            if changed:
                self.mark_progress(
                    "validation evidence changed"
                )
                self._validation_fingerprint = fingerprint
                return ProgressDecision(
                    meaningful=True,
                    stuck=False,
                    no_progress_count=0,
                )

        signature = self._call_signature(
            tool_name,
            arguments,
        )
        result_fingerprint = self._result_fingerprint(
            tool_name,
            arguments,
            result,
        )
        repeated = (
            self._observations.get(signature)
            == result_fingerprint
        )
        self._observations[signature] = result_fingerprint
        self.no_progress_count += 1

        stuck = (
            self.no_progress_count
            >= self.max_no_progress_steps
        )

        if stuck:
            self.recovery_active = True
            pressure = (
                " while context pressure is critical"
                if context_critical
                else ""
            )
            repeat_text = (
                " Repeated unchanged observations were detected."
                if repeated
                else ""
            )
            self.last_reason = (
                f"Reached {self.no_progress_count} consecutive "
                f"tool actions without a task-state transition"
                f"{pressure}.{repeat_text}"
            )

        return ProgressDecision(
            meaningful=False,
            stuck=stuck,
            no_progress_count=self.no_progress_count,
            repeated_observation=repeated,
            reason=self.last_reason if stuck else None,
        )

    def restriction_reason(
        self,
        tool_name: str,
        arguments: dict | None = None,
    ) -> str | None:
        if not self.recovery_active:
            return None

        if tool_name in self.RECOVERY_ALLOWED_TOOLS:
            return None

        if (
            tool_name == "run_command"
            and str(
                (arguments or {}).get(
                    "purpose",
                    "diagnostic",
                )
            ).strip().lower()
            == "acceptance"
        ):
            return None

        return self.RECOVERY_INSTRUCTION

    @classmethod
    def _tool_made_progress(
        cls,
        tool_name: str,
        result,
    ) -> bool:
        if not getattr(result, "success", False):
            return False

        data = getattr(result, "data", {}) or {}

        if tool_name in cls.EDIT_TOOLS:
            return True

        if tool_name == "complete_plan_step":
            return bool(data.get("completed"))

        if tool_name == "replan":
            return bool(data.get("replanned"))

        return False

    @staticmethod
    def _call_signature(
        tool_name: str,
        arguments: dict,
    ) -> str:
        encoded = json.dumps(
            arguments,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return f"{tool_name}|{encoded}"

    @staticmethod
    def _result_fingerprint(
        tool_name: str,
        arguments: dict,
        result,
    ) -> str:
        data = dict(
            getattr(result, "data", {})
            or {}
        )
        data.pop("safety", None)
        payload = {
            "tool": tool_name,
            "arguments": arguments,
            "success": getattr(result, "success", False),
            "summary": getattr(result, "summary", ""),
            "error": getattr(result, "error", None),
            "data": data,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return sha1(
            encoded.encode("utf-8")
        ).hexdigest()
