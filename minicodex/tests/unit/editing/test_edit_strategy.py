from ....agent.editing import EditStrategyHint


def test_edit_strategy_uses_write_for_new_file_and_symbol_for_python():
    hint = EditStrategyHint()

    assert hint.choose(target_path="app.py", file_exists=False).tool_name == "write_file"
    assert hint.choose(
        target_path="app.py", file_exists=True, symbol_known=True
    ).tool_name == "replace_symbol"


def test_edit_strategy_prefers_bounded_existing_file_edits():
    hint = EditStrategyHint()

    assert hint.choose(
        target_path="app.py", file_exists=True, line_region_known=True
    ).tool_name == "replace_lines"
    assert hint.choose(
        target_path="app.py", file_exists=True, exact_text_known=True
    ).tool_name == "patch_file"
