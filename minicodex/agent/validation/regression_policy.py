"""Proportional regression requirements for the current change scope."""

from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath


class RegressionRequirement(str, Enum):
    REQUIRED = "required"
    NOT_APPLICABLE = "not_applicable"
    RELEVANT_ONLY = "relevant_only"
    UNKNOWN = "unknown"


class RegressionPolicy:
    _NON_PRODUCT_PREFIXES = (
        "try_code/",
        "examples/",
        "docs/",
    )
    _CORE_PREFIXES = (
        "minicodex/agent/",
        "minicodex/tools/",
        "minicodex/evaluation/",
    )

    def requirement_for(
        self,
        *,
        mode,
        changed_paths=(),
        default: RegressionRequirement | None = None,
    ) -> RegressionRequirement:
        paths = tuple(
            self._normalize(path)
            for path in changed_paths
            if str(path).strip()
        )

        mode_value = getattr(mode, "value", mode)

        if mode_value == "complex":
            return RegressionRequirement.REQUIRED

        if paths and all(self._is_non_product(path) for path in paths):
            return RegressionRequirement.NOT_APPLICABLE

        if any(path.startswith(self._CORE_PREFIXES) for path in paths):
            return (
                RegressionRequirement.RELEVANT_ONLY
                if mode_value != "complex"
                else RegressionRequirement.REQUIRED
            )

        if mode_value == "standard":
            return RegressionRequirement.RELEVANT_ONLY

        if mode_value == "fast" and paths:
            return RegressionRequirement.RELEVANT_ONLY

        return default or RegressionRequirement.UNKNOWN

    @classmethod
    def _is_non_product(cls, path: str) -> bool:
        name = PurePosixPath(path).name.casefold()
        return path.startswith(cls._NON_PRODUCT_PREFIXES) or name.startswith(
            "readme"
        )

    @staticmethod
    def _normalize(path) -> str:
        return str(path).strip().replace("\\", "/").lstrip("./")
