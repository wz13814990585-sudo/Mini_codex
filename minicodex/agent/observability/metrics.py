from dataclasses import dataclass, field
import time

from ...llm.types import TokenUsage


@dataclass
class ExecutionMetrics:
    """Behavior metrics for one task; these never influence execution."""

    execution_mode: str | None = None
    intent: str | None = None
    llm_call_count: int = 0
    agent_steps: int = 0
    tool_call_count: int = 0
    inspection_tool_count: int = 0
    edit_tool_count: int = 0
    validation_tool_count: int = 0
    calls_before_first_edit: int | None = None
    calls_before_first_validation: int | None = None
    replan_count: int = 0
    action_required_trigger_count: int = 0
    rollback_count: int = 0
    max_steps_exhausted: bool = False
    total_prompt_tokens: int = 0
    final_outcome: str | None = None
    final_completion_reason: str | None = None
    final_reason_code: str | None = None
    false_completion: bool = False
    wrong_edit: bool = False
    routing_llm_calls: int = 0
    routing_prompt_tokens: int = 0
    routing_completion_tokens: int = 0
    routing_latency: float = 0.0
    routing_fallback_count: int = 0
    routing_prompt_version: str = ""
    routing_model: str = ""
    requirements_llm_calls: int = 0
    requirements_tokens: int = 0
    semantic_judge_llm_calls: int = 0
    semantic_judge_tokens: int = 0
    semantic_judge_latency: float = 0.0
    semantic_judge_prompt_version: str = ""
    mode_escalations: int = 0
    late_plan_activations: int = 0
    repair_attempts: int = 0
    validation_runs: int = 0
    flaky_reruns: int = 0
    premature_rollbacks_prevented: int = 0
    repeated_action_count: int = 0
    no_progress_detections: int = 0
    recovery_successes: int = 0
    duration_seconds: float = 0.0
    time_to_first_edit: float | None = None
    inspections_before_first_edit: int | None = None
    searches_before_first_edit: int = 0
    redundant_reads: int = 0
    redundant_searches: int = 0
    wrong_validation_target_count: int = 0
    cost_usd: float | None = None
    _started: float = field(default_factory=time.monotonic, repr=False)
    _observations: set = field(default_factory=set, repr=False)

    def reset(self, execution_mode: str | None = None, *, intent: str | None = None) -> None:
        self._started = time.monotonic()
        self.time_to_first_edit = None
        self.inspections_before_first_edit = None
        self.searches_before_first_edit = 0
        self.redundant_reads = self.redundant_searches = 0
        self.wrong_validation_target_count = 0
        self.cost_usd = None
        self._observations.clear()
        self.execution_mode = execution_mode
        self.intent = intent
        self.llm_call_count = 0
        self.agent_steps = 0
        self.tool_call_count = 0
        self.inspection_tool_count = 0
        self.edit_tool_count = 0
        self.validation_tool_count = 0
        self.calls_before_first_edit = None
        self.calls_before_first_validation = None
        self.replan_count = 0
        self.action_required_trigger_count = 0
        self.rollback_count = 0
        self.max_steps_exhausted = False
        self.total_prompt_tokens = 0
        self.final_outcome = None
        self.final_completion_reason = None
        self.final_reason_code = None
        self.false_completion = False
        self.wrong_edit = False
        self.routing_llm_calls = 0
        self.routing_prompt_tokens = 0
        self.routing_completion_tokens = 0
        self.routing_latency = 0.0
        self.routing_fallback_count = 0
        self.routing_prompt_version = ""
        self.routing_model = ""
        self.requirements_llm_calls = 0
        self.requirements_tokens = 0
        self.semantic_judge_llm_calls = 0
        self.semantic_judge_tokens = 0
        self.semantic_judge_latency = 0.0
        self.semantic_judge_prompt_version = ""
        self.mode_escalations = 0
        self.late_plan_activations = 0
        self.repair_attempts = 0
        self.validation_runs = 0
        self.flaky_reruns = 0
        self.premature_rollbacks_prevented = 0
        self.repeated_action_count = 0
        self.no_progress_detections = 0
        self.recovery_successes = 0
        self.duration_seconds = 0.0

    def record_tool(
        self,
        tool_name: str,
        *,
        llm_call_count: int,
        arguments: dict | None = None,
        success: bool = True,
        revision: int = 0,
        capabilities: frozenset[str] = frozenset(),
    ) -> None:
        from ..progress import ActionController

        self.tool_call_count += 1
        import json
        signature = (tool_name, json.dumps(arguments or {}, sort_keys=True), revision)
        is_search = "code.search" in capabilities or tool_name in {"search_code", "search_symbol"}
        is_read = "filesystem.read" in capabilities or tool_name == "read_file"
        if signature in self._observations:
            self.redundant_reads += int(is_read)
            self.redundant_searches += int(is_search)
        self._observations.add(signature)
        if self.time_to_first_edit is None and is_search:
            self.searches_before_first_edit += 1
        self.llm_call_count = max(self.llm_call_count, int(llm_call_count))
        if tool_name in ActionController.INSPECTION_TOOLS or capabilities & {"filesystem.read", "code.search", "git.inspect"}:
            self.inspection_tool_count += 1
        if (tool_name in ActionController.EDIT_TOOLS or "code.edit" in capabilities) and success:
            self.edit_tool_count += 1
            if self.calls_before_first_edit is None:
                self.calls_before_first_edit = llm_call_count
                self.time_to_first_edit = time.monotonic() - self._started
                self.inspections_before_first_edit = self.inspection_tool_count
        if tool_name in ActionController.VALIDATION_TOOLS or capabilities & {"test.run", "validation.static_web", "validation.browser", "service.validate"} or (
            tool_name == "run_command"
            and str((arguments or {}).get("purpose", "diagnostic")).lower()
            in {"acceptance", "regression"}
        ):
            self.validation_tool_count += 1
            if self.calls_before_first_validation is None:
                self.calls_before_first_validation = llm_call_count
            self.validation_runs += 1
        if tool_name == "replan":
            self.replan_count += 1

    def finish(self, outcome: str, reason: str, reason_code=None) -> None:
        self.final_outcome = outcome
        self.final_completion_reason = reason
        self.final_reason_code = getattr(reason_code, "value", reason_code)

    def observe_llm(self, *, call_count: int, total_prompt_tokens: int) -> None:
        self.llm_call_count = max(0, int(call_count))
        self.total_prompt_tokens = max(0, int(total_prompt_tokens))

    def record_rollback(self) -> None:
        self.rollback_count += 1

    def record_routing(self, telemetry) -> None:
        self.routing_llm_calls = int(getattr(telemetry, "calls", 0))
        self.routing_prompt_tokens = int(getattr(telemetry, "prompt_tokens", 0))
        self.routing_completion_tokens = int(getattr(telemetry, "completion_tokens", 0))
        self.routing_latency = float(getattr(telemetry, "latency_seconds", 0.0))
        self.routing_fallback_count = int(getattr(telemetry, "fallback_count", 0))
        self.routing_prompt_version = str(getattr(telemetry, "prompt_version", ""))
        self.routing_model = str(getattr(telemetry, "model", ""))

    def record_requirements(self, telemetry) -> None:
        self.requirements_llm_calls = int(getattr(telemetry, "calls", 0))
        self.requirements_tokens = int(getattr(telemetry, "prompt_tokens", 0)) + int(
            getattr(telemetry, "completion_tokens", 0)
        )

    def record_semantic_judge(self, telemetry) -> None:
        self.semantic_judge_llm_calls += int(getattr(telemetry, "calls", 0))
        self.semantic_judge_tokens += int(getattr(telemetry, "prompt_tokens", 0)) + int(
            getattr(telemetry, "completion_tokens", 0)
        )
        self.semantic_judge_latency += float(getattr(telemetry, "latency_seconds", 0.0))
        self.semantic_judge_prompt_version = str(getattr(telemetry, "prompt_version", ""))

    @property
    def repeated_action_rate(self) -> float:
        return self.repeated_action_count / self.tool_call_count if self.tool_call_count else 0.0

    @property
    def validation_to_edit_ratio(self):
        return self.validation_tool_count / max(1, self.edit_tool_count)


@dataclass
class TokenMetrics:
    """
    Track token usage for the current Agent task.

    The metrics object accumulates token usage from
    multiple LLM calls during one task.
    """

    total: TokenUsage = field(
        default_factory=TokenUsage
    )

    call_count: int = 0

    # =========================================================
    # Reset
    # =========================================================

    def reset(self) -> None:
        """
        Reset all token metrics for a new task.
        """

        self.total = TokenUsage()
        self.call_count = 0

    # =========================================================
    # Record
    # =========================================================

    def record(
        self,
        usage: TokenUsage,
    ) -> None:
        """
        Add one LLM call's token usage to the task total.
        """

        self.total.prompt_tokens += (
            usage.prompt_tokens
        )

        self.total.completion_tokens += (
            usage.completion_tokens
        )

        self.total.total_tokens += (
            usage.total_tokens
        )

        self.call_count += 1
