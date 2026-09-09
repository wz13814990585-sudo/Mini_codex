"""Compatibility exports for process sandboxing."""

from .safety.sandbox import SandboxLimits, SandboxResult, SandboxRunner

__all__ = ["SandboxLimits", "SandboxResult", "SandboxRunner"]
