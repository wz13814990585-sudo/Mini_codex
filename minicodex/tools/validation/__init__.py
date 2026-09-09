"""Static and browser-backed validation tools."""

from .validate_browser_app import ValidateBrowserAppTool
from .validate_static_web import ValidateStaticWebTool

__all__ = ["ValidateBrowserAppTool", "ValidateStaticWebTool"]
