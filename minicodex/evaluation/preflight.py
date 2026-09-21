"""Selected-case-aware deterministic environment checks for Benchmark V1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib.metadata
import importlib.util
import shutil
import sys


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    available: bool
    detail: str
    kind: str


@dataclass(frozen=True)
class BenchmarkPreflightResult:
    checks: tuple[PreflightCheck, ...]
    required_executables: tuple[str, ...]
    required_python_modules: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return all(check.available for check in self.checks)

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "required_executables": list(self.required_executables),
            "required_python_modules": list(self.required_python_modules),
            "checks": [asdict(check) for check in self.checks],
        }

    def render(self) -> str:
        lines = ["Benchmark 环境预检", ""]
        for check in self.checks:
            state = "通过" if check.available else "失败"
            lines.append(f"{check.name:<18} {state:<4} {check.detail}")
        lines.extend(["", f"就绪 = {str(self.ready).lower()}"])
        return "\n".join(lines)


def benchmark_preflight(fixtures, *, executable_finder=None, module_finder=None) -> BenchmarkPreflightResult:
    """Check only infrastructure needed by the selected immutable fixtures."""

    executable_finder = executable_finder or shutil.which
    module_finder = module_finder or importlib.util.find_spec
    required_executables = tuple(sorted({
        name for fixture in fixtures for name in fixture.required_executables
    }))
    fixture_modules = {
        name for fixture in fixtures for name in fixture.required_python_modules
    }
    required_modules = tuple(sorted({"pytest", *fixture_modules}))

    checks = [PreflightCheck(
        name="python",
        available=bool(sys.executable),
        detail=f"{sys.executable} ({sys.version.split()[0]})",
        kind="executable",
    )]
    for name in required_modules:
        available = module_finder(name) is not None
        detail = "无法导入"
        if available:
            try:
                detail = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                detail = "可导入"
        checks.append(PreflightCheck(name, available, detail, "python_module"))
    for name in required_executables:
        path = executable_finder(name)
        checks.append(PreflightCheck(name, bool(path), path or "未在 PATH 中找到", "executable"))

    return BenchmarkPreflightResult(
        checks=tuple(checks),
        required_executables=required_executables,
        required_python_modules=required_modules,
    )
