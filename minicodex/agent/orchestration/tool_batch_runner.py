"""Ordered provider batches; domain decisions belong to ToolEventAdapter."""
from .tool_call_runner import ToolCallRunner
from .tool_event_adapter import ToolEventAdapter
from .tool_batch_result import ToolBatchResult


class ToolBatchRunner:
    def __init__(self, call_runner=None):
        self.call_runner = call_runner or ToolCallRunner()
        self.adapter = ToolEventAdapter(self.call_runner)

    def run(self, agent, assistant_message, messages, current_plan_step=None):
        tool_calls = list(getattr(assistant_message, "tool_calls", None) or ())
        messages.append(assistant_message.model_dump(exclude_none=True))
        runs, evidence_items, signals = [], [], []
        for index, tool_call in enumerate(tool_calls):
            decision = self.adapter.process(
                agent, tool_call, index=index, tool_calls=tool_calls, messages=messages,
                current_plan_step=current_plan_step, runs=runs,
                evidence_items=evidence_items, signals=signals,
            )
            if decision is not None:
                return decision
        return ToolBatchResult(tuple(runs), tuple(evidence_items), tuple(signals))
