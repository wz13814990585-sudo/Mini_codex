"""Task authorization state; semantic classification lives in task_router."""

from enum import Enum


class TaskIntent(str, Enum):
    INFORMATIONAL = "informational"
    INSPECT_ONLY = "inspect_only"
    MODIFY = "modify"
