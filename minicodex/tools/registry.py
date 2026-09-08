"""Tool registry."""

from .base import BaseTool


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
