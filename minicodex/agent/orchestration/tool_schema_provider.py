"""Provide tool schemas for one provider turn."""


class ToolSchemaProvider:
    def build(self, agent) -> list[dict]:
        if hasattr(agent, "get_tool_schemas"):
            return agent.get_tool_schemas()
        return agent.registry.get_schemas()
