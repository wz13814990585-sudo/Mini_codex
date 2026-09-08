"""Compose deterministic intent classification and complexity routing."""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..execution_mode import ExecutionMode
from ...utils.paths import normalize_repo_path
from .complexity import ComplexityRouter
from .intent import IntentClassifier, TaskIntent


@dataclass(frozen=True)
class TaskRoute:
    intent: TaskIntent
    mode: ExecutionMode
    reason: str
    signals: tuple[str, ...] = ()
    target_paths: tuple[str, ...] = ()

    @property
    def requires_coding_action(self) -> bool:
        return self.intent == TaskIntent.MODIFY


@dataclass(frozen=True)
class RoutingRule:
    name: str
    mode: ExecutionMode
    description: str


class TaskRouter:
    _PATH = re.compile(
        r"(?<![\w.-])([\w.-]+(?:[/\\][\w.-]+)+|"
        r"[\w.-]+\.(?:py|html|css|js|md|toml|json|ya?ml)|README(?:\.md)?)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        intent_classifier: IntentClassifier | None = None,
        complexity_router: ComplexityRouter | None = None,
    ) -> None:
        self.intent_classifier = intent_classifier or IntentClassifier()
        self.complexity_router = complexity_router or ComplexityRouter()

    def route(self, user_request: str, repo_state=None) -> TaskRoute:
        del repo_state
        text = str(user_request or "").strip()
        targets = tuple(dict.fromkeys(self._extract_paths(text)))
        intent = self.intent_classifier.classify(text)
        complexity = self.complexity_router.route(text, targets)
        return TaskRoute(
            intent=intent,
            mode=complexity.mode,
            reason=f"{intent.value}: {complexity.reason}",
            signals=(*complexity.signals, f"intent:{intent.value}"),
            target_paths=targets,
        )

    @classmethod
    def _extract_paths(cls, text: str) -> list[str]:
        return [
            normalize_repo_path(match.group(1).rstrip(".,:;)"))
            for match in cls._PATH.finditer(text)
        ]
