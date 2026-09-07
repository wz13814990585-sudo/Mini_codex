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
