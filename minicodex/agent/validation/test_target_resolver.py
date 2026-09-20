"""Resolve source artifacts to real pytest targets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...utils.paths import normalize_repo_path, resolve_workspace_path
from .test_index import TestIndex


@dataclass(frozen=True)
class TestTargetResolution:
    selected_path: str | None
    source_path: str | None
    confidence: str
    reason: str
    acceptance_supported: bool
    purpose: str = "regression"


class TestTargetResolver:
    """Find an existing test without ever treating source as acceptance."""

    __test__ = False

    def __init__(self, workspace: str | Path = ".", test_index: TestIndex | None = None) -> None:
        self.workspace = Path(workspace).resolve()
        self.test_index = test_index or TestIndex(self.workspace)

    def resolve(
        self, source_paths: tuple[str, ...], *, revision: object = 0
    ) -> TestTargetResolution:
        normalized = tuple(
            dict.fromkeys(
                normalize_repo_path(str(path).strip())
                for path in source_paths
                if str(path).strip()
            )
        )
        for source in normalized:
            if self.is_test_path(source) and self._exists(source):
                return TestTargetResolution(
                    source, source, "high", "请求的产物本身就是已有的 pytest 目标。", True,
                    "acceptance",
                )

        for source in normalized:
            if not source.lower().endswith(".py"):
                continue
            for candidate in self._candidates(source):
                if self._exists(candidate):
                    return TestTargetResolution(
                        candidate,
                        source,
                        "high",
                        f"已将源文件 {source} 映射到已有测试 {candidate}。",
                        True,
                        "acceptance",
                    )

        for source in normalized:
            if not source.lower().endswith(".py"):
                continue
            indexed = self.test_index.tests_for(source, revision=revision)
            if indexed:
                return TestTargetResolution(
                    indexed[0],
                    source,
                    "medium",
                    f"AST 导入/引用索引将 {source} 关联到 {indexed[0]}。",
                    False,
                    "regression",
                )

        for source in normalized:
            if not source.lower().endswith(".py"):
                continue
            nearby = self.test_index.same_package_tests(source, revision=revision)
            if nearby:
                return TestTargetResolution(
                    nearby[0],
                    source,
                    "low",
                    f"已为 {source} 选择附近包回归测试 {nearby[0]}。",
                    False,
                    "regression",
                )

        for directory in ("minicodex/tests", "tests"):
            if (self.workspace / directory).is_dir():
                return TestTargetResolution(
                    directory,
                    normalized[0] if normalized else None,
                    "low",
                    "未找到聚焦测试；仅有回归目录可用。",
                    False,
                    "regression",
                )

        return TestTargetResolution(
            None,
            normalized[0] if normalized else None,
            "none",
            "无法为请求的源文件解析到已有 pytest 目标。",
            False,
            "regression",
        )

    @staticmethod
    def is_test_path(path: str) -> bool:
        candidate = Path(str(path).split("::", 1)[0])
        name = candidate.name.lower()
        return (
            "tests" in {part.lower() for part in candidate.parts}
            or name.startswith("test_")
            or name.endswith("_test.py")
        )

    def _candidates(self, source: str) -> tuple[str, ...]:
        path = Path(source)
        stem = path.stem
        candidates = [
            path.with_name(f"test_{stem}.py"),
            path.parent / "tests" / f"test_{stem}.py",
            Path("minicodex/tests") / f"test_{stem}.py",
            Path("tests") / f"test_{stem}.py",
        ]
        return tuple(dict.fromkeys(candidate.as_posix() for candidate in candidates))

    def _exists(self, relative: str) -> bool:
        try:
            candidate = resolve_workspace_path(self.workspace, relative.split("::", 1)[0])
        except (ValueError, OSError):
            return False
        return candidate.is_file()
