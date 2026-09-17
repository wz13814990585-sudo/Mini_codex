"""Context budgeting, compaction, and repository navigation."""

from .budget import ContextBudget, ContextPressure
from .message_compaction import compact_messages, compact_messages_for_pressure
from .repo_map import RepoMap
from .symbol_index import Symbol, SymbolIndex
from .project_execution_environment import ProjectExecutionEnvironment

__all__ = [
    "ContextBudget",
    "ContextPressure",
    "RepoMap",
    "Symbol",
    "SymbolIndex",
    "ProjectExecutionEnvironment",
    "compact_messages",
    "compact_messages_for_pressure",
]
