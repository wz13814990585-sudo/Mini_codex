from ..agent.progress import ProgressController, ProgressKind


def test_validation_fingerprint_only_advances_on_better_evidence():
    progress = ProgressController(max_validation_no_progress=2)

    baseline = progress.track_validation(3, "acceptance:targeted:test", 1)
    unchanged = progress.track_validation(3, "acceptance:targeted:test", 1)
    improved = progress.track_validation(1, "acceptance:targeted:test", 2)
    passed = progress.track_validation(0, "acceptance:targeted:test", 2)
    repeated_pass = progress.track_validation(0, "acceptance:targeted:test", 2)

    assert baseline.signal.kind == ProgressKind.OBSERVATION
    assert unchanged.signal.kind == ProgressKind.NONE
    assert improved.signal.kind == ProgressKind.ADVANCED
    assert passed.signal.kind == ProgressKind.ADVANCED
    assert repeated_pass.signal.kind == ProgressKind.NONE


def test_validation_regression_is_not_meaningful_progress():
    progress = ProgressController()
    progress.track_validation(1, "regression:targeted:test", 1)

    regressed = progress.track_validation(3, "regression:targeted:test", 2)

    assert regressed.signal.kind == ProgressKind.REGRESSED
    assert regressed.meaningful_progress is False
