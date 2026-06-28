from app.config import settings
from app.trajectory.candidates import CandidateTrack


def test_snapshot_settings_present_with_sane_defaults():
    assert settings.snapshot_soft_cap == 120
    assert 0.0 <= settings.snapshot_relevance_floor <= 1.0
    assert settings.snapshot_min_per_artist == 2
    assert settings.snapshot_max_per_artist == 4
    assert settings.snapshot_album_cap == 2
    assert 0.0 < settings.snapshot_banger_percentile < 1.0
    assert settings.snapshot_pool_limit >= settings.snapshot_soft_cap * 4


def test_candidate_track_has_snapshot_score_default():
    t = CandidateTrack(
        id="1", title="x", artist_name="a", artist_id="a1",
        album_name="al", album_id="al1", year=1985, duration_ms=200000,
    )
    assert t.snapshot_score == 0.0
