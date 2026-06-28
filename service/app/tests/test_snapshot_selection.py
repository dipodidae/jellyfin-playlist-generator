from app.trajectory.candidates import CandidateTrack
from app.snapshot.selection import (
    relevance, compute_snapshot_scores, is_banger, select_artist_tracks,
)


def _t(tid, artist, album, gm=0.9, dark=0.8, banger=0.5, leg=0.5):
    t = CandidateTrack(
        id=tid, title=f"t{tid}", artist_name=artist, artist_id=artist,
        album_name=album, album_id=album, year=1985, duration_ms=200000,
        darkness=dark,
    )
    t.genre_match_score = gm
    t.banger_score = banger
    t.album_legitimacy_score = leg
    return t


def test_relevance_blends_genre_and_mood():
    # genre fit 1.0, perfect dark match (target 0.8, track 0.8) → high
    t = _t("1", "a", "x", gm=1.0, dark=0.8)
    r = relevance(t, base_darkness=0.8, mood_weight=0.3)
    assert r > 0.9
    # same genre fit, mood far off → lower
    t2 = _t("2", "a", "x", gm=1.0, dark=0.1)
    assert relevance(t2, base_darkness=0.8, mood_weight=0.3) < r


def test_compute_snapshot_scores_applies_floor_and_sets_score():
    keep = _t("1", "a", "x", gm=0.9)
    drop = _t("2", "a", "x", gm=0.0, dark=0.0, banger=0.0, leg=0.0)
    out = compute_snapshot_scores([keep, drop], base_darkness=0.8,
                                  mood_weight=0.3, floor=0.35)
    assert [t.id for t in out] == ["1"]
    assert out[0].snapshot_score > 0.0


def test_is_banger_relative_to_artist_distribution():
    hi = _t("1", "a", "x", banger=0.9)
    lo = _t("2", "a", "y", banger=0.1)
    arts = [hi, lo]
    assert is_banger(hi, arts, percentile=0.6) is True
    assert is_banger(lo, arts, percentile=0.6) is False


def test_select_artist_tracks_caps_count_and_album_and_includes_banger():
    # 5 tracks, 4 from album "x" (one a banger), 1 from album "y"
    tracks = [
        _t("1", "a", "x", banger=0.95, gm=0.9, leg=0.9),  # the banger
        _t("2", "a", "x", banger=0.1, gm=0.8, leg=0.8),
        _t("3", "a", "x", banger=0.1, gm=0.8, leg=0.7),
        _t("4", "a", "x", banger=0.1, gm=0.8, leg=0.6),
        _t("5", "a", "y", banger=0.1, gm=0.85, leg=0.85),
    ]
    compute_snapshot_scores(tracks, base_darkness=0.8, mood_weight=0.3, floor=0.0)
    picked = select_artist_tracks(tracks, min_n=2, max_n=4, album_cap=2,
                                  banger_percentile=0.6)
    assert 2 <= len(picked) <= 4
    assert "1" in {t.id for t in picked}                       # banger always in
    assert sum(1 for t in picked if t.album_id == "x") <= 2    # album cap honored
    assert "5" in {t.id for t in picked}                       # other album surfaces
