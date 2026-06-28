from app.trajectory.candidates import CandidateTrack
from app.snapshot.selection import apply_soft_cap, shuffle_no_adjacent_artist


def _t(tid, artist, score):
    t = CandidateTrack(
        id=tid, title=f"t{tid}", artist_name=artist, artist_id=artist,
        album_name="al", album_id=f"al{tid}", year=1985, duration_ms=200000,
    )
    t.snapshot_score = score
    return t


def test_apply_soft_cap_keeps_strongest_artists_first():
    by_artist = {
        "a": [_t("1", "a", 0.9), _t("2", "a", 0.85)],   # best 0.9
        "b": [_t("3", "b", 0.5), _t("4", "b", 0.45)],   # best 0.5
        "c": [_t("5", "c", 0.7), _t("6", "c", 0.65)],   # best 0.7
    }
    out = apply_soft_cap(by_artist, cap=4)
    ids = {t.id for t in out}
    assert len(out) == 4
    assert {"1", "2", "5", "6"}.issubset(ids)   # a (0.9) + c (0.7) chosen over b
    assert "3" not in ids and "4" not in ids


def test_apply_soft_cap_allows_partial_last_artist():
    by_artist = {
        "a": [_t("1", "a", 0.9), _t("2", "a", 0.85)],
        "c": [_t("5", "c", 0.7), _t("6", "c", 0.65)],
    }
    out = apply_soft_cap(by_artist, cap=3)
    assert len(out) == 3  # a fully (2) + one from c


def test_apply_soft_cap_returns_all_when_under_cap():
    by_artist = {"a": [_t("1", "a", 0.9)], "b": [_t("2", "b", 0.5)]}
    out = apply_soft_cap(by_artist, cap=120)
    assert len(out) == 2


def test_shuffle_never_places_same_artist_adjacent():
    tracks = (
        [_t(str(i), "a", 0.5) for i in range(5)]
        + [_t(str(i), "b", 0.5) for i in range(5, 8)]
        + [_t(str(i), "c", 0.5) for i in range(8, 10)]
    )
    out = shuffle_no_adjacent_artist(tracks, seed=42)
    assert len(out) == len(tracks)
    assert {t.id for t in out} == {t.id for t in tracks}
    for prev, cur in zip(out, out[1:]):
        assert prev.artist_id != cur.artist_id


def test_shuffle_is_deterministic_for_a_seed():
    tracks = [_t(str(i), chr(97 + i % 3), 0.5) for i in range(9)]
    assert [t.id for t in shuffle_no_adjacent_artist(tracks, seed=7)] == \
           [t.id for t in shuffle_no_adjacent_artist(tracks, seed=7)]
