from app.trajectory.sequencer import mfcc_continuity, vocal_jump_score


def test_mfcc_continuity_identical_is_high():
    v = [1.0, 2.0, 3.0] + [0.0] * 9
    assert mfcc_continuity(v, v) > 0.95


def test_mfcc_continuity_far_is_low():
    a = [0.0] * 12
    b = [50.0] * 12
    assert mfcc_continuity(a, b) < 0.2


def test_mfcc_continuity_missing_returns_none():
    assert mfcc_continuity(None, [0.0] * 12) is None


def test_vocal_jump_score():
    # same instrumentalness → smooth (high)
    assert vocal_jump_score(0.9, 0.9) > 0.95
    # vocal↔instrumental whiplash → low
    assert vocal_jump_score(0.05, 0.95) < 0.3
    assert vocal_jump_score(None, 0.5) is None
