from dataclasses import dataclass
from .tool_call_runner import ToolCallRun
from ..progress import ProgressSignal
from ..reason_codes import ReasonCode

@dataclass(frozen=True)
class ToolBatchResult:
    runs: tuple[ToolCallRun, ...]
    validation_evidence: tuple = ()
    progress_signals: tuple[ProgressSignal, ...] = ()
    restart: bool = False
    early_stop: str | None = None
    followup_message: str | None = None
    completion_finished: bool = False
    reason_code: ReasonCode | None = None
