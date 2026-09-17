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
    retry_safe: bool = False
    idempotent: bool = False


class ToolRegistry:
    # Production built-ins declare capabilities themselves. This adapter only
    # labels legacy third-party/test tools at the registry boundary; callers
    # consume the resulting capability, never this table.
    _LEGACY_CAPABILITIES = {
        "list_files": {"filesystem.read"}, "read_file": {"filesystem.read", "file.read"},
        "search_code": {"code.search"}, "search_symbol": {"code.search", "code.symbol"},
        "write_file": {"filesystem.write", "code.edit"}, "patch_file": {"filesystem.write", "code.edit"},
        "replace_lines": {"filesystem.write", "code.edit"}, "replace_symbol": {"filesystem.write", "code.edit"},
        "run_command": {"process.run"}, "run_tests": {"test.run"},
        "validate_static_web": {"validation.static_web"}, "validate_browser_app": {"validation.browser"},
        "validate_service": {"service.validate"}, "install_python_package": {"dependency.install"},
        "git_status": {"git.inspect"}, "git_diff": {"git.inspect"}, "replan": {"plan.control"},
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
        return declared or frozenset(self._LEGACY_CAPABILITIES.get(tool.name, ()))

    def tool_names_for_capability(self, capability: str) -> tuple[str, ...]:
        """Return registered tools that explicitly provide one capability."""
        return tuple(name for name in self._tools if capability in self.capabilities_for(name))

    @property
    def available_capabilities(self) -> frozenset[str]:
        return frozenset(
            capability
            for name in self._tools
            for capability in self.capabilities_for(name)
        )

    def metadata_for(self, tool_or_name) -> ToolMetadata:
        """Return backend-neutral execution metadata for local or future tools."""

        tool = self.get(tool_or_name) if isinstance(tool_or_name, str) else tool_or_name
        capabilities = self.capabilities_for(tool)
        declared = getattr(tool, "metadata", None)
        if isinstance(declared, ToolMetadata):
            return declared
        if "dependency.install" in capabilities:
            side_effect, risk, timeout_class = (
                SideEffectClass.DEPENDENCY_INSTALL, ToolRisk.HIGH, "long"
            )
        elif "filesystem.write" in capabilities or "code.edit" in capabilities:
            side_effect, risk, timeout_class = (
                SideEffectClass.WORKSPACE_WRITE, ToolRisk.MEDIUM, "short"
            )
        elif capabilities & {"process.run", "test.run", "validation.browser", "service.validate"}:
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
            retry_safe=side_effect == SideEffectClass.READ_ONLY,
            idempotent=side_effect == SideEffectClass.READ_ONLY,
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
