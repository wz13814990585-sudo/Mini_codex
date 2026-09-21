"""Machine-checkable local plan-step reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ...utils.paths import resolve_workspace_path


@dataclass(frozen=True)
class CriterionResult:
    kind: str
    definitive: bool
    satisfied: bool
    message: str


@dataclass(frozen=True)
class StepEvaluation:
    machine_checkable: bool
    satisfied: bool
    criteria: list[CriterionResult] = field(
        default_factory=list
    )


class PlanProgressReconciler:
    """Evaluate explicit predicates without making semantic guesses."""

    def __init__(
        self,
        workspace: str | Path = ".",
    ):
        self.workspace = Path(workspace).resolve()

    def evaluate_step(
        self,
        step,
        *,
        validation_state=None,
    ) -> StepEvaluation:
        criteria = list(
            getattr(
                step,
                "acceptance_criteria",
                [],
            )
            or []
        )

        if not criteria:
            return StepEvaluation(
                machine_checkable=False,
                satisfied=False,
            )

        results = [
            self._evaluate_criterion(
                criterion,
                validation_state=validation_state,
            )
            for criterion in criteria
        ]
        definitive = all(
            result.definitive
            for result in results
        )

        return StepEvaluation(
            machine_checkable=definitive,
            satisfied=(
                definitive
                and all(
                    result.satisfied
                    for result in results
                )
            ),
            criteria=results,
        )

    def _evaluate_criterion(
        self,
        criterion: dict,
        *,
        validation_state,
    ) -> CriterionResult:
        kind = str(
            criterion.get("type", "")
        ).strip().lower()
        path_value = str(
            criterion.get("path", "")
        ).strip()

        if kind == "file_exists":
            target = self._resolve(path_value)
            satisfied = bool(
                target
                and target.is_file()
            )
            return CriterionResult(
                kind=kind,
                definitive=target is not None,
                satisfied=satisfied,
                message=(
                    f"file {path_value} "
                    + ("exists" if satisfied else "does not exist")
                ),
            )

        if kind in {"contains_text", "contains_all"}:
            target = self._resolve(path_value)
            if target is None or not target.is_file():
                return CriterionResult(
                    kind=kind,
                    definitive=True,
                    satisfied=False,
                    message=f"file {path_value} is unavailable",
                )

            try:
                source = target.read_text(encoding="utf-8")
            except Exception as error:
                return CriterionResult(
                    kind=kind,
                    definitive=False,
                    satisfied=False,
                    message=(
                        f"could not read {path_value}: {error}"
                    ),
                )

            if kind == "contains_text":
                values = [criterion.get("text", "")]
            else:
                values = criterion.get("texts", [])

            if not isinstance(values, list):
                values = []
            normalized = [
                str(value)
                for value in values
                if str(value)
            ]
            if not normalized:
                return CriterionResult(
                    kind=kind,
                    definitive=False,
                    satisfied=False,
                    message="criterion contains no text predicates",
                )

            missing = [
                value
                for value in normalized
                if value not in source
            ]
            return CriterionResult(
                kind=kind,
                definitive=True,
                satisfied=not missing,
                message=(
                    "all required text is present"
                    if not missing
                    else f"missing text: {missing}"
                ),
            )

        if kind in {
            "static_web_validation",
            "metric_at_least",
        }:
            evidence = getattr(
                validation_state,
                "latest_evidence",
                None,
            )
            revision = getattr(
                validation_state,
                "edit_revision",
                None,
            )
            current = bool(
                evidence
                and evidence.tool_name == "validate_static_web"
                and evidence.edit_revision == revision
                and (
                    not path_value
                    or evidence.path == path_value
                )
            )

            if not current:
                return CriterionResult(
                    kind=kind,
                    definitive=False,
                    satisfied=False,
                    message="current static-web evidence is unavailable",
                )

            if kind == "static_web_validation":
                satisfied = (
                    evidence.outcome.value
                    == "passed"
                )
                return CriterionResult(
                    kind=kind,
                    definitive=True,
                    satisfied=satisfied,
                    message=(
                        "static-web validation passed"
                        if satisfied
                        else "static-web validation did not pass"
                    ),
                )

            metric = str(
                criterion.get("metric", "")
            ).strip()
            try:
                minimum = int(
                    criterion.get("minimum", 0)
                )
                actual = int(
                    evidence.details.get(metric, 0)
                )
            except (TypeError, ValueError):
                return CriterionResult(
                    kind=kind,
                    definitive=False,
                    satisfied=False,
                    message="metric criterion is invalid",
                )
            return CriterionResult(
                kind=kind,
                definitive=bool(metric),
                satisfied=bool(metric) and actual >= minimum,
                message=(
                    f"{metric}={actual}, required={minimum}"
                ),
            )

        return CriterionResult(
            kind=kind or "unknown",
            definitive=False,
            satisfied=False,
            message="criterion type is not supported",
        )

    def _resolve(
        self,
        path: str,
    ) -> Path | None:
        if not path:
            return None

        try:
            return resolve_workspace_path(
                self.workspace,
                path,
            )
        except (ValueError, OSError):
            return None
