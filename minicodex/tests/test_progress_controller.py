from ..agent.progress import ProgressController


def test_interleaved_duplicate_calls_are_counted():
    progress = ProgressController(
        max_same_tool_repeats=2
    )

    assert progress.check_duplicate_tool_call(
        "search_code",
        {"query": "player"},
    )[0] is True

    progress.check_duplicate_tool_call(
        "search_code",
        {"query": "enemy"},
    )

    assert progress.check_duplicate_tool_call(
        "search_code",
        {"query": "player"},
    )[0] is True

    allowed, reason = progress.check_duplicate_tool_call(
        "search_code",
        {"query": "player"},
    )

    assert allowed is False
    assert "repeated" in reason


def test_inspection_nudge_fires_once_per_window():
    progress = ProgressController(
        progress_window=3
    )

    progress.record_action("read_file")
    progress.record_action("search_code")
    assert progress.consume_inspection_nudge() is False

    progress.record_action("search_symbol")
    assert progress.consume_inspection_nudge() is True
    assert progress.consume_inspection_nudge() is False


def test_edit_resets_inspection_streak():
    progress = ProgressController(
        progress_window=3
    )

    progress.record_action("read_file")
    progress.record_action("search_code")
    progress.record_action("patch_file")
    progress.record_action("read_file")

    assert progress.consume_inspection_nudge() is False


def test_meaningful_progress_resets_duplicate_phase():
    progress = ProgressController(
        max_same_tool_repeats=1
    )
    arguments = {"path": "game.html"}

    assert progress.check_duplicate_tool_call(
        "read_file",
        arguments,
    )[0] is True
    assert progress.check_duplicate_tool_call(
        "read_file",
        arguments,
    )[0] is False

    progress.mark_meaningful_progress()

    assert progress.check_duplicate_tool_call(
        "read_file",
        arguments,
    )[0] is True
