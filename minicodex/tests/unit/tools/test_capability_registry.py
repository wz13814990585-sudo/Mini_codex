from ....tools.registry import ToolRegistry


class Tool:
    def __init__(self, name, capabilities=()):
        self.name = name
        self.capabilities = frozenset(capabilities)

    def to_schema(self):
        return {"type": "function", "function": {"name": self.name}}


def test_registry_filters_declared_and_compatibility_capabilities():
    registry = ToolRegistry()
    registry.register(Tool("read_file"))
    registry.register(Tool("custom_reader", {"filesystem.read"}))
    registry.register(Tool("write_file"))

    names = {
        schema["function"]["name"]
        for schema in registry.get_schemas(capabilities={"filesystem.read"})
    }

    assert names == {"read_file", "custom_reader"}
    assert "write_file" not in names
