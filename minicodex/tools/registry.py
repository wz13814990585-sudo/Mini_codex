"""Capability-oriented tool registry."""

from dataclasses import dataclass
from enum import Enum

from .base import BaseTool


class SideEffectClass(str, Enum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    PROCESS_EXECUTION = "process_execution"
    DEPENDENCY_INSTALL = "dependency_install"
    DESTRUCTIVE = "destructive"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"


class ToolRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    capabilities: frozenset[str]
    risk: ToolRisk
    side_effect: SideEffectClass
    read_only: bool
    timeout_class: str
    backend: str


class ToolRegistry:

    _NAME_CAPABILITIES = {
        "list_files": {"filesystem.read"},
        "read_file": {"filesystem.read"},
        "search_code": {"code.search"},
        "search_symbol": {"code.search"},
        "write_file": {"filesystem.write", "code.edit"},
        "patch_file": {"filesystem.write", "code.edit"},
        "replace_lines": {"filesystem.write", "code.edit"},
        "replace_symbol": {"filesystem.write", "code.edit"},
        "run_command": {"process.run"},
        "run_tests": {"test.run"},
        "validate_static_web": {"validation.static_web"},
        "validate_browser_app": {"validation.browser"},
        "install_python_package": {"dependency.install"},
        "git_status": {"git.inspect"},
        "git_diff": {"git.inspect"},
        "complete_plan_step": {"plan.control"},
        "replan": {"plan.control"},
    }

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:

        if tool.name in self._tools:
            raise ValueError(
                f"Tool '{tool.name}' is already registered."
            )

        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:

        tool = self._tools.get(name)

        if tool is None:
            raise ValueError(
                f"Tool '{name}' not found."
            )

        return tool

    def capabilities_for(self, tool_or_name) -> frozenset[str]:
        tool = self.get(tool_or_name) if isinstance(tool_or_name, str) else tool_or_name
        declared = frozenset(getattr(tool, "capabilities", ()) or ())
        return declared or frozenset(self._NAME_CAPABILITIES.get(tool.name, ()))

    def metadata_for(self, tool_or_name) -> ToolMetadata:
        """Return backend-neutral execution metadata for local or future tools."""

        tool = self.get(tool_or_name) if isinstance(tool_or_name, str) else tool_or_name
        capabilities = self.capabilities_for(tool)
        if "dependency.install" in capabilities:
            side_effect, risk, timeout_class = (
                SideEffectClass.DEPENDENCY_INSTALL, ToolRisk.HIGH, "long"
            )
        elif "filesystem.write" in capabilities or "code.edit" in capabilities:
            side_effect, risk, timeout_class = (
                SideEffectClass.WORKSPACE_WRITE, ToolRisk.MEDIUM, "short"
            )
        elif "process.run" in capabilities or "test.run" in capabilities:
            side_effect, risk, timeout_class = (
                SideEffectClass.PROCESS_EXECUTION, ToolRisk.MEDIUM, "long"
            )
        else:
            side_effect, risk, timeout_class = (
                SideEffectClass.READ_ONLY, ToolRisk.LOW, "short"
            )
        return ToolMetadata(
            name=tool.name,
            capabilities=capabilities,
            risk=risk,
            side_effect=side_effect,
            read_only=side_effect == SideEffectClass.READ_ONLY,
            timeout_class=timeout_class,
            backend=str(getattr(tool, "backend", "local")),
        )

    def get_schemas(
        self,
        *,
        names: set[str] | frozenset[str] | None = None,
        capabilities: set[str] | frozenset[str] | None = None,
    ) -> list[dict]:

        required = frozenset(capabilities or ())

        return [
            tool.to_schema()
            for tool in self._tools.values()
            if (names is None or tool.name in names)
            and (not required or bool(self.capabilities_for(tool) & required))
        ]

    def execute(
        self,
        name: str,
        arguments: dict
    ):

        tool = self.get(name)

        return tool.execute(**arguments)
