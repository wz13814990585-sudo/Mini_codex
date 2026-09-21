"""Reusable, bounded repository knowledge; deliberately contains no task state."""
from dataclasses import dataclass
from pathlib import Path
import ast
import json
import os
import re
import tomllib

from .repo_map import DEFAULT_IGNORED_DIRS
from .symbol_index import SymbolIndex
from ..validation.test_index import TestIndex


@dataclass(frozen=True)
class ProjectProfile:
    languages: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    package_manager: str = "unknown"
    manifests: tuple[str, ...] = ()
    source_roots: tuple[str, ...] = ()
    test_roots: tuple[str, ...] = ()
    test_framework: str = "unknown"
    commands: tuple[tuple[str, str], ...] = ()
    configs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodebaseConventions:
    observations: tuple[str, ...] = ()
    example_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChangeImpact:
    targets: tuple[str, ...]
    imports: tuple[str, ...] = ()
    dependents: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    neighbors: tuple[str, ...] = ()


class ChangeImpactResolver:
    def resolve(self, session, targets, *, limit=20):
        targets = tuple(dict.fromkeys(targets))[:limit]
        imports, dependents, tests, neighbors = set(), set(), set(), set()
        for path in targets:
            imports.update(session.imports.get(path, ()))
            dependents.update(p for p, deps in session.imports.items() if path in deps)
            tests.update(session.test_index.tests_for(path, revision=session.revision))
            neighbors.update(p for p in session.paths if Path(p).parent == Path(path).parent and p != path)
        return ChangeImpact(targets, tuple(sorted(imports))[:limit], tuple(sorted(dependents))[:limit],
                            tuple(sorted(tests))[:limit], tuple(sorted(neighbors))[:limit])


class WorkspaceSession:
    """A session can serve follow-up tasks, but cannot satisfy their requirements."""

    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.paths = ()
        self.revision = 0
        self.profile = ProjectProfile()
        self.conventions = CodebaseConventions()
        self.imports = {}
        self.recent_paths = ()
        self.priority_paths = ()
        self.test_index = TestIndex(self.workspace)
        self.symbol_index = SymbolIndex(self.workspace)
        self._fingerprint = None
        self.build_count = 0
        self.changed_paths = ()
        self._dirty_paths: set[str] = set()
        self._structural_dirty = False
        self._unchanged_checks = 0
        self.external_check_interval = 8

    def prioritize(self, paths) -> None:
        """Bias the next bounded scan toward explicit/current task artifacts."""
        normalized = tuple(str(path).replace("\\", "/").lstrip("./") for path in paths or () if str(path).strip())
        self.priority_paths = tuple(dict.fromkeys((*normalized, *self.recent_paths, *self.priority_paths)))[:80]

    def refresh(self, *, full=False, periodic=False):
        """Refresh dirty agent paths now; sample external changes infrequently."""
        if self._fingerprint is not None and self._dirty_paths and not self._structural_dirty:
            return self._refresh_dirty()
        if self._fingerprint is not None and periodic and not full and not self._structural_dirty:
            self._unchanged_checks += 1
            if self._unchanged_checks < self.external_check_interval:
                self.changed_paths = ()
                return False
        self._unchanged_checks = 0
        paths = []
        seen = set()
        for relative in self.priority_paths:
            candidate = self.workspace / relative
            if candidate.is_file() and not candidate.is_symlink():
                paths.append(relative)
                seen.add(relative)
        for base, dirs, files in os.walk(self.workspace, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in DEFAULT_IGNORED_DIRS and not d.startswith("."))
            for name in sorted(files):
                path = Path(base) / name
                relative = path.relative_to(self.workspace).as_posix()
                if not path.is_symlink() and relative not in seen:
                    paths.append(relative)
                    seen.add(relative)
                if len(paths) >= 1500:
                    break
            if len(paths) >= 1500:
                break
        fingerprint = []
        for p in paths:
            try:
                s = (self.workspace / p).stat()
                fingerprint.append((p, s.st_mtime_ns, s.st_size))
            except OSError:
                pass
        # Scan order may be relevance-prioritized; identity/freshness must not
        # treat a different traversal order as an external repository edit.
        fingerprint.sort()
        if tuple(fingerprint) == self._fingerprint:
            self.changed_paths = ()
            return False
        before = {p: (mtime, size) for p, mtime, size in (self._fingerprint or ())}
        after = {p: (mtime, size) for p, mtime, size in fingerprint}
        self.changed_paths = tuple(sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p)))
        self._fingerprint = tuple(fingerprint)
        self.paths = tuple(p for p, _, _ in fingerprint)
        self.revision += 1
        self.build_count += 1
        self.profile = self._profile()
        self.conventions = self._scan_sources()
        self._dirty_paths.clear()
        self._structural_dirty = False
        return True

    def invalidate(self, path, *, structural=False):
        """Record an owned mutation without discarding the whole session index."""
        normalized = str(path).strip().replace("\\", "/").lstrip("./")
        if not normalized:
            self._structural_dirty = True
            return
        self._dirty_paths.add(normalized)
        self._structural_dirty = self._structural_dirty or structural
        self.recent_paths = tuple(dict.fromkeys((normalized, *self.recent_paths)))[:20]

    def _refresh_dirty(self):
        before = {p: (mtime, size) for p, mtime, size in self._fingerprint}
        after = dict(before)
        for path in self._dirty_paths:
            try:
                stat = (self.workspace / path).stat()
            except OSError:
                after.pop(path, None)
            else:
                after[path] = (stat.st_mtime_ns, stat.st_size)
        changed = tuple(sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path)))
        self._dirty_paths.clear()
        if not changed:
            self.changed_paths = ()
            return False
        self.changed_paths = changed
        self._fingerprint = tuple(sorted((path, *facts) for path, facts in after.items()))
        self.paths = tuple(path for path, _, _ in self._fingerprint)
        self.revision += 1
        self.build_count += 1
        if any(Path(path).name in {"pyproject.toml", "package.json", "requirements.txt", "setup.py"} for path in changed):
            self.profile = self._profile()
        source_changes = tuple(path for path in changed if path.endswith((".py", ".js", ".jsx", ".ts", ".tsx")))
        if source_changes:
            self.conventions = self._scan_sources(source_changes, incremental=True)
        return True

    def _read(self, path):
        try:
            file = self.workspace / path
            if file.stat().st_size > 128_000:
                return ""
            return file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""

    def _profile(self):
        paths = set(self.paths)
        manifests = tuple(p for p in ("pyproject.toml", "package.json", "requirements.txt", "setup.py") if p in paths)
        languages = tuple(name for ext, name in (((".py",), "Python"), ((".js", ".jsx"), "JavaScript"), ((".ts", ".tsx"), "TypeScript"), ((".html",), "HTML"))
                          if any(p.endswith(ext) for p in paths))
        frameworks, commands = [], []
        manager, tests = "unknown", "unknown"
        if "pyproject.toml" in paths or "requirements.txt" in paths:
            manager = "uv" if "uv.lock" in paths else "pip"
            content = self._read("pyproject.toml") + self._read("requirements.txt")
            frameworks.extend(x for x in ("fastapi", "flask", "django") if x in content.casefold())
            try:
                config = tomllib.loads(self._read("pyproject.toml"))
            except tomllib.TOMLDecodeError:
                config = {}
            settings = config.get("tool", {})
            if "pytest" in content or any("test_" in p for p in paths):
                tests = "pytest"
                commands.append(("test", "python -m pytest"))
            for tool, command in (("ruff", "ruff check ."), ("mypy", "mypy .")):
                if tool in settings:
                    commands.append(("lint" if tool == "ruff" else "typecheck", command))
        if "package.json" in paths:
            manager = "pnpm" if "pnpm-lock.yaml" in paths else "yarn" if "yarn.lock" in paths else "npm"
            try:
                package = json.loads(self._read("package.json"))
            except (ValueError, TypeError):
                package = {}
            if not isinstance(package, dict):
                package = {}
            deps = {key: value for field in ("dependencies", "devDependencies")
                    for key, value in (package.get(field) if isinstance(package.get(field), dict) else {}).items()}
            frameworks.extend(x for x in ("react", "next", "vue", "express", "vite") if x in deps)
            tests = next((x for x in ("vitest", "jest", "mocha") if x in deps), tests)
            commands.extend((name, f"{manager} run {name}") for name in ("test", "build", "lint", "typecheck", "start", "dev")
                            if isinstance(package.get("scripts"), dict) and name in package["scripts"])
        roots = sorted({p.split("/")[0] for p in paths if "/" in p})
        test_roots = tuple(sorted({str(Path(p).parent) for p in paths
                                  if Path(p).name.startswith("test_") or ".test." in p or ".spec." in p or p.endswith("_test.py")}))[:12]
        return ProjectProfile(languages, tuple(frameworks), manager, manifests,
                              tuple(r for r in roots if r not in {"tests", "docs"})[:8],
                              test_roots, tests, tuple(commands),
                              tuple(p for p in paths if "config" in Path(p).name)[:12])

    def _scan_sources(self, paths=None, *, incremental=False):
        observations = set(self.conventions.observations) if incremental else set()
        examples = list(self.conventions.example_paths) if incremental else []
        if not incremental:
            self.imports = {}
        scan_paths = paths or self.paths
        ordered = tuple(dict.fromkeys((*self.priority_paths, *self.recent_paths, *scan_paths)))
        for path in (p for p in ordered if p in self.paths and p.endswith((".py", ".js", ".jsx", ".ts", ".tsx"))):
            if len(examples) >= 80:
                break
            text = self._read(path)
            if path not in examples:
                examples.append(path)
            deps = []
            if path.endswith(".py"):
                try:
                    tree = ast.parse(text)
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    modules = []
                    if isinstance(node, ast.ImportFrom):
                        parts = list(Path(path).parts[:-1])
                        if node.level:
                            parts = parts[:len(parts) - node.level + 1] if node.level <= len(parts) else []
                            module = ".".join((*parts, *((node.module or "").split(".") if node.module else ())))
                        else:
                            module = node.module or ""
                        modules = [module, *(f"{module}.{alias.name}" for alias in node.names)]
                    elif isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                    for module in modules:
                        base = module.replace(".", "/")
                        for prefix in ("", "src/", "lib/"):
                            deps.extend(candidate for candidate in (prefix + base + ".py", prefix + base + "/__init__.py") if candidate in self.paths)
                    if isinstance(node, ast.AsyncFunctionDef):
                        observations.add("async functions present")
                    if isinstance(node, ast.FunctionDef) and node.returns:
                        observations.add("return annotations present")
                    if isinstance(node, ast.FunctionDef) and "_" in node.name:
                        observations.add("snake_case functions present")
                    if isinstance(node, ast.Try):
                        observations.add("exception handlers present")
                if "@pytest.fixture" in text:
                    observations.add("pytest fixtures used")
                if "logging.getLogger" in text:
                    observations.add("module loggers used")
            else:
                for module in re.findall(r"(?:from\s+|require\()[\"'](\.[^\"']+)", text):
                    base = Path(os.path.normpath(str(Path(path).parent / module))).as_posix()
                    deps.extend(p for p in (base, base + ".ts", base + ".tsx", base + ".js", base + ".jsx", base + "/index.ts", base + "/index.js") if p in self.paths)
            self.imports[path] = tuple(dict.fromkeys(deps))
        return CodebaseConventions(tuple(sorted(observations)), tuple(examples[:6]))

    def render(self, targets):
        if self._fingerprint is None:
            self.refresh()
        impact = ChangeImpactResolver().resolve(self, targets)
        return (f"Project: {', '.join(self.profile.languages) or 'unknown'}; "
                f"manager={self.profile.package_manager}; tests={self.profile.test_framework}; "
                f"commands={dict(self.profile.commands)}.\n"
                f"Observed conventions: {', '.join(self.conventions.observations) or 'none yet'}.\n"
                f"Navigation LOCATE -> EXPAND -> READ: targets={impact.targets}; "
                f"imports={impact.imports}; dependents={impact.dependents}; tests={impact.tests}; "
                f"neighbors={impact.neighbors[:5]}.")
