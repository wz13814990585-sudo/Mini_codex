"""Explicit action progress and comparable validation trends."""

import json

from dataclasses import dataclass
from enum import Enum


class ValidationStatus(
    str,
    Enum,
):

    UNKNOWN = "unknown"
    PASSED = "passed"
    IMPROVED = "improved"
    UNCHANGED = "unchanged"
    REGRESSED = "regressed"
    CHANGED = "changed"
    UNSTABLE = "unstable"


class ProgressKind(str, Enum):
    ADVANCED = "advanced"
    OBSERVATION = "observation"
    NONE = "none"
    REGRESSED = "regressed"


@dataclass(frozen=True)
class ProgressSignal:
    kind: ProgressKind
    reason: str = ""

    @property
    def advanced(self) -> bool:
        return self.kind == ProgressKind.ADVANCED


@dataclass(frozen=True)
class ValidationFingerprint:
    outcome: str
    failed_count: int | None
    purpose: str = "unknown"
    scope: str = "unknown"
    path: str = ""
    failure_ids: tuple[str, ...] = ()


@dataclass
class ValidationProgress:

    status: ValidationStatus

    previous_failed: int | None = None

    current_failed: int | None = None

    previous_revision: int | None = None

    current_revision: int | None = None

    validation_key: str | None = None

    message: str | None = None

    stalled: bool = False

    signal: ProgressSignal = ProgressSignal(ProgressKind.NONE)

    @property
    def meaningful_progress(
        self,
    ) -> bool:

        return self.signal.advanced

    @property
    def crossed_revision(
        self,
    ) -> bool:

        return bool(
            self.previous_revision
            is not None
            and self.current_revision
            is not None
            and self.current_revision
            > self.previous_revision
        )


class ProgressController:

    def __init__(
        self,
        max_same_tool_repeats: int = 2,
        progress_window: int | None = None,
        max_validation_no_progress: int = 2,
    ):

        # ``progress_window`` is intentionally ignored by this controller.
        # Generic stall detection now belongs exclusively to ActionController.
        del progress_window

        self.max_same_tool_repeats = (
            max_same_tool_repeats
        )

        self.max_validation_no_progress = (
            max_validation_no_progress
        )

        # =====================================================
        # Duplicate Tool State
        # =====================================================

        self.last_tool_signature = None

        self.same_tool_repeat_count = 0

        # Counts survive interleaved calls until real progress
        # resets this controller.
        self._tool_signature_counts: dict[tuple[str, str, int], int] = {}

        # =====================================================
        # Last Observed Validation
        #
        # Kept for human-readable summaries.
        # =====================================================

        self.last_validation_failed_count: (
            int | None
        ) = None

        self.last_validation_key: (
            str | None
        ) = None

        self.last_validation_revision: (
            int | None
        ) = None

        self.validation_no_progress_count = 0

        # =====================================================
        # Comparable Validation Series
        #
        # key -> (failed_count, edit_revision)
        # =====================================================

        self._validation_series: dict[str, tuple[ValidationFingerprint, int | None]] = {}

    # =========================================================
    # Reset
    # =========================================================

    def reset(
        self,
        new_task: bool = False,
    ) -> None:

        self.last_tool_signature = None

        self.same_tool_repeat_count = 0

        self._tool_signature_counts.clear()

        self.last_validation_failed_count = None

        self.last_validation_key = None

        self.last_validation_revision = None

        self.validation_no_progress_count = 0

        self._validation_series.clear()

    def mark_meaningful_progress(
        self,
    ) -> None:
        """Start a fresh action phase without losing validation history."""

        self.last_tool_signature = None
        self.same_tool_repeat_count = 0
        self._tool_signature_counts.clear()
    # =========================================================
    # Duplicate Tool Detection
    # =========================================================

    def check_duplicate_tool_call(
        self,
        tool_name: str,
        arguments: dict,
        *,
        workspace_revision: int = 0,
    ) -> tuple[
        bool,
        str | None,
    ]:

        signature = (
            tool_name,
            json.dumps(
                arguments,
                sort_keys=True,
                ensure_ascii=False,
            ),
            max(0, int(workspace_revision)),
        )

        signature_count = (
            self._tool_signature_counts.get(
                signature,
                0,
            )
            + 1
        )

        self._tool_signature_counts[
            signature
        ] = signature_count

        if (
            signature
            == self.last_tool_signature
        ):

            self.same_tool_repeat_count += 1

        else:

            self.last_tool_signature = (
                signature
            )

            self.same_tool_repeat_count = 0

        if (
            signature_count
            > self.max_same_tool_repeats
        ):

            return (
                False,
                (
                    "同一工具以相同参数被重复调用，"
                    "且未带来有意义的进展。"
                ),
            )

        return (
            True,
            None,
        )

    # =========================================================
    # Validation Progress
    # =========================================================

    def track_validation(
        self,
        failed_count: int | None,
        validation_key: str | None = None,
        edit_revision: int | None = None,
        *,
        outcome: str | None = None,
        purpose: str = "unknown",
        scope: str = "unknown",
        path: str = "",
        fingerprint: ValidationFingerprint | None = None,
        failure_ids: tuple[str, ...] = (),
        unstable: bool = False,
    ) -> ValidationProgress:

        fingerprint = fingerprint or ValidationFingerprint(
            outcome=outcome or ("passed" if failed_count == 0 else "failed" if failed_count is not None else "inconclusive"),
            failed_count=failed_count,
            purpose=purpose,
            scope=scope,
            path=path,
            failure_ids=tuple(failure_ids),
        )

        if unstable:
            return ValidationProgress(
                status=ValidationStatus.UNSTABLE,
                current_failed=failed_count,
                current_revision=edit_revision,
                validation_key=validation_key,
                message="可比验证结果相互矛盾，表明验证不稳定。",
                signal=ProgressSignal(ProgressKind.OBSERVATION, "验证疑似不稳定。"),
            )

        # =====================================================
        # Cannot Interpret
        # =====================================================

        if (
            failed_count
            is None
        ):

            return ValidationProgress(
                status=(
                    ValidationStatus.UNKNOWN
                ),
                current_revision=(
                    edit_revision
                ),
                validation_key=(
                    validation_key
                ),
                signal=ProgressSignal(ProgressKind.OBSERVATION, "验证结果不确定。"),
            )

        normalized_key = (
            validation_key
            or "__unknown_validation__"
        )

        # =====================================================
        # Human-readable Latest State
        # =====================================================

        self.last_validation_failed_count = (
            failed_count
        )

        self.last_validation_key = (
            validation_key
        )

        self.last_validation_revision = (
            edit_revision
        )

        previous = (
            self._validation_series
            .get(
                normalized_key
            )
        )

        # Always record this observation for the next
        # comparable validation.
        self._validation_series[
            normalized_key
        ] = (
            fingerprint,
            edit_revision,
        )

        # =====================================================
        # First Observation Of This Series
        # =====================================================

        if (
            previous
            is None
        ):

            self.validation_no_progress_count = 0

            if (
                failed_count
                == 0
            ):

                return ValidationProgress(
                    status=(
                        ValidationStatus.PASSED
                    ),
                    previous_failed=None,
                    current_failed=0,
                    previous_revision=None,
                    current_revision=(
                        edit_revision
                    ),
                    validation_key=(
                        validation_key
                    ),
                    message=(
                        "验证成功。"
                    ),
                    signal=ProgressSignal(ProgressKind.ADVANCED, "验证从未知变为通过。"),
                )

            return ValidationProgress(
                status=(
                    ValidationStatus.UNKNOWN
                ),
                previous_failed=None,
                current_failed=(
                    failed_count
                ),
                previous_revision=None,
                current_revision=(
                    edit_revision
                ),
                validation_key=(
                    validation_key
                ),
                message=(
                    "已记录首次可比验证："
                    f"{failed_count} 项失败。"
                ),
                signal=ProgressSignal(ProgressKind.OBSERVATION, "首次失败验证基线。"),
            )

        (
            previous_fingerprint,
            previous_revision,
        ) = previous
        previous_failed = previous_fingerprint.failed_count

        # =====================================================
        # Passed
        # =====================================================

        if failed_count == 0:

            self.validation_no_progress_count = 0

            return ValidationProgress(
                status=(
                    ValidationStatus.PASSED
                ),
                previous_failed=(
                    previous_failed
                ),
                current_failed=0,
                previous_revision=(
                    previous_revision
                ),
                current_revision=(
                    edit_revision
                ),
                validation_key=(
                    validation_key
                ),
                message=(
                    "验证成功。"
                ),
                signal=(
                    ProgressSignal(ProgressKind.ADVANCED, "可比验证从失败变为通过。")
                    if previous_failed not in {None, 0}
                    else ProgressSignal(ProgressKind.NONE, "可比验证仍为通过。")
                ),
            )

        # =====================================================
        # Improved
        # =====================================================

        if (
            failed_count
            < previous_failed
        ):

            self.validation_no_progress_count = 0

            return ValidationProgress(
                status=(
                    ValidationStatus.IMPROVED
                ),
                previous_failed=(
                    previous_failed
                ),
                current_failed=(
                    failed_count
                ),
                previous_revision=(
                    previous_revision
                ),
                current_revision=(
                    edit_revision
                ),
                validation_key=(
                    validation_key
                ),
                message=(
                    "验证有改善："
                    f"{previous_failed} 项失败 -> "
                    f"{failed_count} 项失败。"
                ),
                signal=ProgressSignal(ProgressKind.ADVANCED, "可比失败数量下降。"),
            )

        # =====================================================
        # Unchanged
        # =====================================================

        if failed_count == previous_failed:

            previous_ids = set(previous_fingerprint.failure_ids)
            current_ids = set(fingerprint.failure_ids)
            if previous_ids and current_ids and previous_ids != current_ids:
                new_ids = current_ids - previous_ids
                resolved_ids = previous_ids - current_ids
                status = ValidationStatus.REGRESSED if new_ids else ValidationStatus.CHANGED
                return ValidationProgress(
                    status=status,
                    previous_failed=previous_failed,
                    current_failed=failed_count,
                    previous_revision=previous_revision,
                    current_revision=edit_revision,
                    validation_key=validation_key,
                    message=(
                        f"失败身份发生变化：已解决 {len(resolved_ids)} 项，"
                        f"新增 {len(new_ids)} 项。"
                    ),
                    signal=ProgressSignal(
                        ProgressKind.REGRESSED if new_ids else ProgressKind.OBSERVATION,
                        "可比失败身份已变化。",
                    ),
                )

            self.validation_no_progress_count += 1

            stalled = (
                self.validation_no_progress_count
                >= self.max_validation_no_progress
            )

            return ValidationProgress(
                status=(
                    ValidationStatus.UNCHANGED
                ),
                previous_failed=(
                    previous_failed
                ),
                current_failed=(
                    failed_count
                ),
                previous_revision=(
                    previous_revision
                ),
                current_revision=(
                    edit_revision
                ),
                validation_key=(
                    validation_key
                ),
                message=(
                    "验证无变化："
                    f"仍有 {failed_count} 项测试失败。"
                ),
                stalled=(
                    stalled
                ),
                signal=ProgressSignal(ProgressKind.NONE, "可比失败数量未变化。"),
            )

        # =====================================================
        # Regressed
        # =====================================================

        self.validation_no_progress_count += 1

        stalled = (
            self.validation_no_progress_count
            >= self.max_validation_no_progress
        )

        return ValidationProgress(
            status=(
                ValidationStatus.REGRESSED
            ),
            previous_failed=(
                previous_failed
            ),
            current_failed=(
                failed_count
            ),
            previous_revision=(
                previous_revision
            ),
            current_revision=(
                edit_revision
            ),
            validation_key=(
                validation_key
            ),
            message=(
                "验证回退："
                f"{previous_failed} 项失败 -> "
                f"{failed_count} 项失败。"
            ),
            stalled=(
                stalled
            ),
            signal=ProgressSignal(ProgressKind.REGRESSED, "可比失败数量上升。"),
        )
