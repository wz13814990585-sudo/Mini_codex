"""Compatibility export for controlled dependency installation."""

from .execution.install_python_package import (
    IMPORT_NAME_PATTERN,
    PACKAGE_SPEC_PATTERN,
    InstallPythonPackageTool,
)

__all__ = ["IMPORT_NAME_PATTERN", "PACKAGE_SPEC_PATTERN", "InstallPythonPackageTool"]
