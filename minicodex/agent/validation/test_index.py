"""Revision-cached index connecting source modules to pytest files."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path

from ...utils.paths import normalize_repo_path
from ..context.repo_map import DEFAULT_IGNORED_DIRS


@dataclass(frozen=True)
class IndexedTest:
    path: str
    imported_sources: tuple[str, ...]
    referenced_paths: tuple[str, ...]


class TestIndex:
    """Build an AST-based source→test map once per workspace revision."""

    __test__ = False

    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()
        self._revision: object = object()
        self._tests: tuple[IndexedTest, ...] = ()
        self._source_to_tests: dict[str, tuple[str, ...]] = {}
        self.build_count = 0

    def refresh(self, revision: object = 0) -> None:
        if revision == self._revision:
            return
        records = tuple(self._scan_test(path) for path in self._test_files())
        mapping: dict[str, list[str]] = {}
        for record in records:
            for source in (*record.imported_sources, *record.referenced_paths):
                mapping.setdefault(source, [])
                if record.path not in mapping[source]:
                    mapping[source].append(record.path)
        self._tests = records
        self._source_to_tests = {
            source: tuple(paths) for source, paths in mapping.items()
        }
        self._revision = revision
        self.build_count += 1

    def tests_for(self, source_path: str, *, revision: object = 0) -> tuple[str, ...]:
        self.refresh(revision)
        source = normalize_repo_path(source_path)
        matches = list(self._source_to_tests.get(source, ()))
        if source.endswith("/__init__.py"):
            matches.extend(self._source_to_tests.get(source.removesuffix("/__init__.py") + ".py", ()))
        return tuple(dict.fromkeys(matches))

    def same_package_tests(
        self, source_path: str, *, revision: object = 0
    ) -> tuple[str, ...]:
        self.refresh(revision)
        source = Path(normalize_repo_path(source_path))
        parent_name = source.parent.name.casefold()
        return tuple(
            record.path
            for record in self._tests
            if parent_name and parent_name in {part.casefold() for part in Path(record.path).parts}
        )

    def all_tests(self, *, revision: object = 0) -> tuple[str, ...]:
        self.refresh(revision)
        return tuple(record.path for record in self._tests)

    def _test_files(self) -> tuple[Path, ...]:
        found: list[Path] = []
        visited = 0
        for base, dirs, files in os.walk(self.workspace, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in DEFAULT_IGNORED_DIRS and not d.startswith("."))
            for name in sorted(files):
                visited += 1
                path = Path(base) / name
                if name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py")) and not path.is_symlink():
                    found.append(path)
                if visited >= 2000:
                    return tuple(sorted(found))
        return tuple(sorted(found))

    def _scan_test(self, path: Path) -> IndexedTest:
        relative = path.relative_to(self.workspace).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeError, SyntaxError):
            return IndexedTest(relative, (), ())

        imports: list[str] = []
        references: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolved = self._module_path(alias.name)
                    if resolved:
                        imports.append(resolved)
            elif isinstance(node, ast.ImportFrom):
                module = self._absolute_import_module(path, node)
                for candidate in (module, *(f"{module}.{alias.name}" for alias in node.names)):
                    resolved = self._module_path(candidate)
                    if resolved:
                        imports.append(resolved)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = normalize_repo_path(node.value.strip())
                if value.endswith(".py") and (self.workspace / value).is_file():
                    references.append(value)
        return IndexedTest(
            relative,
            tuple(dict.fromkeys(imports)),
            tuple(dict.fromkeys(references)),
        )

    def _absolute_import_module(self, test_path: Path, node: ast.ImportFrom) -> str:
        if not node.level:
            return node.module or ""
        relative = test_path.relative_to(self.workspace).with_suffix("")
        package = list(relative.parts[:-1])
        trim = max(0, node.level - 1)
        if trim:
            package = package[:-trim]
        if node.module:
            package.extend(node.module.split("."))
        return ".".join(package)

    def _module_path(self, module: str) -> str | None:
        if not module:
            return None
        base = Path(*module.split("."))
        candidates = tuple(candidate for root in (Path(), Path("src"), Path("lib"))
                           for candidate in (root / base.with_suffix(".py"), root / base / "__init__.py"))
        for candidate in candidates:
            if (self.workspace / candidate).is_file():
                return candidate.as_posix()
        return None
