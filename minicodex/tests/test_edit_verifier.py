from pathlib import Path

import pytest

from ..tools.edit_verifier import (
    EditVerifier,
)


def test_edit_verifier_rejects_noop():

    with pytest.raises(
        ValueError,
        match="would not change",
    ):

        EditVerifier.ensure_changed(
            "hello",
            "hello",
        )


def test_edit_verifier_accepts_real_change():

    EditVerifier.ensure_changed(
        "hello",
        "world",
    )


def test_python_candidate_validation():

    path = Path(
        "demo.py"
    )

    result = (
        EditVerifier
        .validate_candidate(
            path,
            (
                "def run():\n"
                "    return 1\n"
            ),
        )
    )

    assert (
        result
        is True
    )


def test_python_candidate_rejects_syntax_error():

    path = Path(
        "demo.py"
    )

    with pytest.raises(
        ValueError,
        match="invalid Python syntax",
    ):

        EditVerifier.validate_candidate(
            path,
            (
                "def run()\n"
                "    return 1\n"
            ),
        )


def test_non_python_skips_ast_validation():

    result = (
        EditVerifier
        .validate_candidate(
            Path(
                "notes.txt"
            ),
            "anything",
        )
    )

    assert (
        result
        is False
    )


def test_post_write_verification(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.py"
    )

    before = (
        "def run():\n"
        "    return 1\n"
    )

    after = (
        "def run():\n"
        "    return 2\n"
    )

    file_path.write_text(
        after
    )

    result = (
        EditVerifier
        .verify_after_write(
            file_path,
            before_content=before,
            expected_content=after,
        )
    )

    assert (
        result.changed
        is True
    )

    assert (
        result.content_verified
        is True
    )

    assert (
        result.syntax_validated
        is True
    )

    assert (
        result.before_sha256
        != result.after_sha256
    )


def test_post_write_detects_wrong_disk_content(
    tmp_path: Path,
):

    file_path = (
        tmp_path
        / "demo.txt"
    )

    file_path.write_text(
        "wrong"
    )

    with pytest.raises(
        RuntimeError,
        match="does not match",
    ):

        EditVerifier.verify_after_write(
            file_path,
            before_content="before",
            expected_content="expected",
        )