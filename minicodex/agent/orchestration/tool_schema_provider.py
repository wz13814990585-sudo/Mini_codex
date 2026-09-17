"""Provide tool schemas for one provider turn."""


class ToolSchemaProvider:
    def build(self, agent) -> list[dict]:
        import copy
        if hasattr(agent, "get_tool_schemas"):
            schemas = copy.deepcopy(agent.get_tool_schemas())
        else:
            schemas = copy.deepcopy(agent.registry.get_schemas())
        for schema in schemas:
            function = schema["function"]
            caps = agent.registry.capabilities_for(function["name"])
            if "code.edit" in caps:
                function["parameters"].setdefault("properties", {})["edit_intent"] = {
                    "type": "object", "description": "Independent expected post-edit state, not the patch mechanism.",
                    "properties": {"path": {"type": "string"}, "expected_text": {"type": "string"},
                                   "removed_text": {"type": "string"}, "symbol": {"type": "string"}},
                    "required": ["path", "expected_text"], "additionalProperties": False,
                }
            if caps & {"test.run", "process.run", "validation.static_web", "validation.browser", "service.validate"}:
                function["parameters"].setdefault("properties", {})["validation_check"] = {
                    "type": "string", "description": "Exact V-id from the current verification contracts."
                }
        return schemas
