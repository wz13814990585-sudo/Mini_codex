from ....agent.validation import TestTargetResolver


def touch(root, relative):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def test_minicodex_source_maps_to_existing_minicodex_test(tmp_path):
    touch(tmp_path, "minicodex/tools/editing/patch_file.py")
    touch(tmp_path, "minicodex/tests/test_patch_file.py")

    result = TestTargetResolver(tmp_path).resolve(
        ("minicodex/tools/editing/patch_file.py",)
    )

    assert result.selected_path == "minicodex/tests/test_patch_file.py"
    assert result.acceptance_supported is True


def test_application_source_maps_to_root_test_directory(tmp_path):
    touch(tmp_path, "app/foo.py")
    touch(tmp_path, "tests/test_foo.py")

    result = TestTargetResolver(tmp_path).resolve(("app/foo.py",))

    assert result.selected_path == "tests/test_foo.py"


def test_no_candidate_never_returns_source_as_pytest_target(tmp_path):
    touch(tmp_path, "app/foo.py")

    result = TestTargetResolver(tmp_path).resolve(("app/foo.py",))

    assert result.selected_path != "app/foo.py"
    assert result.acceptance_supported is False
