"""Verified filesystem editing tools."""

__all__ = [
    "EditVerification",
    "EditVerifier",
    "PatchFileTool",
    "ReplaceLinesTool",
    "ReplaceSymbolTool",
    "WriteFileTool",
]


def __getattr__(name):
    if name in {"EditVerification", "EditVerifier"}:
        from .edit_verifier import EditVerification, EditVerifier

        return {"EditVerification": EditVerification, "EditVerifier": EditVerifier}[name]
    modules = {
        "PatchFileTool": ("patch_file", "PatchFileTool"),
        "ReplaceLinesTool": ("replace_lines", "ReplaceLinesTool"),
        "ReplaceSymbolTool": ("replace_symbol", "ReplaceSymbolTool"),
        "WriteFileTool": ("write_file", "WriteFileTool"),
    }
    if name in modules:
        module_name, attribute = modules[name]
        from importlib import import_module

        return getattr(import_module(f"{__name__}.{module_name}"), attribute)
    raise AttributeError(name)
