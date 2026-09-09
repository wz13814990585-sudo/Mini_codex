"""Safety policy, guarded execution, and process sandboxing."""

from .safety import SafetyDecision, SafetyLevel, SafetyPolicy

__all__ = [
    "SafetyDecision",
    "SafetyLevel",
    "SafetyPolicy",
    "SafetyToolExecutor",
    "SandboxLimits",
    "SandboxResult",
    "SandboxRunner",
]


def __getattr__(name):
    if name == "SafetyToolExecutor":
        from .safety_executor import SafetyToolExecutor

        return SafetyToolExecutor
    if name in {"SandboxLimits", "SandboxResult", "SandboxRunner"}:
        from .sandbox import SandboxLimits, SandboxResult, SandboxRunner

        return {
            "SandboxLimits": SandboxLimits,
            "SandboxResult": SandboxResult,
            "SandboxRunner": SandboxRunner,
        }[name]
    raise AttributeError(name)
