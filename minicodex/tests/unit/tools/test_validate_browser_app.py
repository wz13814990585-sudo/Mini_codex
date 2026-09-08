from ....tools.validate_browser_app import ValidateBrowserAppTool


def test_browser_validator_is_optional_and_names_static_fallback(tmp_path):
    target = tmp_path / "index.html"
    target.write_text("<p>Hello</p>", encoding="utf-8")
    tool = ValidateBrowserAppTool(tmp_path)

    if tool.available():
        return
    result = tool.execute("index.html")

    assert result.success is False
    assert result.data["outcome"] == "inconclusive"
    assert result.data["fallback"] == "validate_static_web"
