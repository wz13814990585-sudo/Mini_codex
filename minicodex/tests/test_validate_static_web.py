import shutil

import pytest

from ..agent.validation import (
    ValidationOutcome,
    ValidationPipeline,
)
from ..tools.validation import (
    ValidateStaticWebTool,
)


NODE = shutil.which("node")


def make_tool(tmp_path):
    return ValidateStaticWebTool(
        workspace=tmp_path,
        node_executable=NODE,
    )


@pytest.mark.skipif(NODE is None, reason="Node.js unavailable")
def test_valid_single_file_game_passes(tmp_path):
    (tmp_path / "game.html").write_text(
        """<!doctype html><html><body>
        <button data-row="0" data-col="0">A</button>
        <script>const f = x => x > 1;</script>
        </body></html>""",
        encoding="utf-8",
    )

    result = make_tool(tmp_path).execute(
        "game.html",
        min_button_count=1,
        min_data_row_count=1,
        min_data_col_count=1,
        require_inline_script=True,
    )

    assert result.success is True
    assert result.data["outcome"] == "passed"
    assert result.data["script_syntax"] == "passed"
    assert result.data["button_count"] == 1


@pytest.mark.skipif(NODE is None, reason="Node.js unavailable")
def test_javascript_syntax_error_fails(tmp_path):
    (tmp_path / "bad.html").write_text(
        "<html><body><script>const = ;</script></body></html>",
        encoding="utf-8",
    )

    result = make_tool(tmp_path).execute(
        "bad.html",
        require_inline_script=True,
    )

    assert result.success is True
    assert result.data["outcome"] == "failed"
    assert result.data["script_syntax"] == "failed"
    assert result.data["errors"]


@pytest.mark.skipif(NODE is None, reason="Node.js unavailable")
def test_missing_data_markers_are_reported(tmp_path):
    (tmp_path / "game.html").write_text(
        "<html><body><button>A</button><script>let x=1;</script></body></html>",
        encoding="utf-8",
    )

    result = make_tool(tmp_path).execute(
        "game.html",
        min_data_row_count=1,
        min_data_col_count=1,
    )

    assert result.data["outcome"] == "failed"
    assert result.data["data_row_count"] == 0
    assert result.data["data_col_count"] == 0
    assert any(
        "data_row_count" in error
        for error in result.data["errors"]
    )


def test_static_web_result_creates_current_acceptance_evidence():
    pipeline = ValidationPipeline()
    pipeline.record_edit()
    result = type("Result", (), {
        "success": True,
        "summary": "passed",
        "data": {
            "outcome": "passed",
            "errors": [],
            "button_count": 36,
        },
    })()

    evidence = pipeline.observe(
        "validate_static_web",
        {"path": "try_code/game.html"},
        result,
    )

    assert evidence.outcome == ValidationOutcome.PASSED
    assert evidence.edit_revision == 1
    assert evidence.details["button_count"] == 36
    assert pipeline.current_acceptance_passed() is True

    pipeline.record_edit()

    assert pipeline.current_acceptance_passed() is False
    assert pipeline.state.latest_evidence is None
