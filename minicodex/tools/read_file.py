"""Compatibility export for the file-reading tool."""

from .filesystem.read_file import DEFAULT_READ_LIMIT, ReadFileTool

__all__ = ["DEFAULT_READ_LIMIT", "ReadFileTool"]
