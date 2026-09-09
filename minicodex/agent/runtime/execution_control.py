"""Task cancellation primitives for MiniCodex."""

from __future__ import annotations

from dataclasses import dataclass
from threading import (
    Event,
    Lock,
)


# =============================================================
# Execution Cancelled
# =============================================================


class ExecutionCancelled(
    RuntimeError
):
    """
    Raised when a running MiniCodex task observes cancellation.

    This is cooperative cancellation.

    Cancellation is checked at deterministic execution
    boundaries such as:

        before LLM calls
        after LLM calls
        before tool execution
        after tool execution

    It does not forcibly kill the Python thread.
    """

    pass


# =============================================================
# Cancellation Snapshot
# =============================================================


@dataclass(frozen=True)
class CancellationSnapshot:

    cancelled: bool

    reason: str | None


# =============================================================
# Cancellation Token
# =============================================================


class CancellationToken:
    """
    Thread-safe cooperative cancellation token.

    One token belongs to one Agent task.
    """

    def __init__(
        self,
    ):

        self._event = (
            Event()
        )

        self._lock = (
            Lock()
        )

        self._reason: (
            str
            | None
        ) = None

    # =========================================================
    # Cancel
    # =========================================================

    def cancel(
        self,
        reason: str = (
            "Task cancelled by caller."
        ),
    ) -> bool:
        """
        Request cancellation.

        Returns True only for the first successful request.
        """

        with self._lock:

            if (
                self._event
                .is_set()
            ):

                return False

            self._reason = (
                str(
                    reason
                )
                .strip()
                or (
                    "Task cancelled by caller."
                )
            )

            self._event.set()

            return True

    # =========================================================
    # State
    # =========================================================

    @property
    def is_cancelled(
        self,
    ) -> bool:

        return (
            self._event
            .is_set()
        )

    @property
    def reason(
        self,
    ) -> str | None:

        with self._lock:

            return (
                self._reason
            )

    def snapshot(
        self,
    ) -> CancellationSnapshot:

        return (
            CancellationSnapshot(
                cancelled=(
                    self.is_cancelled
                ),
                reason=(
                    self.reason
                ),
            )
        )

    # =========================================================
    # Checkpoint
    # =========================================================

    def raise_if_cancelled(
        self,
    ) -> None:

        if not (
            self.is_cancelled
        ):

            return

        raise (
            ExecutionCancelled(
                self.reason
                or (
                    "Task cancelled."
                )
            )
        )
