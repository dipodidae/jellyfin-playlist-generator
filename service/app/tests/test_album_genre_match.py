"""Tests for album genres feeding compute_genre_match_score (P3, C2)."""
from app.trajectory.candidates import CandidateTrack, compute_genre_match_score


def _track(**kw):
    return CandidateTrack(
        id="t", title="x", artist_name="a", artist_id=None,
        album_name="al", album_id=None, year=2000, duration_ms=180000, **kw,
    )


def test_no_album_genres_is_unchanged():
    """Dormant: with no album_genres the score matches the genres-only result."""
    hint = {"shoegaze"}
    t = _track(genres=["shoegaze"])
    base = compute_genre_match_score(t, hint, hint)
    t2 = _track(genres=["shoegaze"], album_genres=[])
    assert compute_genre_match_score(t2, hint, hint) == base


def test_album_genre_contributes_match_when_track_genre_absent():
    """A match found only via album_genres scores > 0 (was 0 before C2)."""
    hint = {"shoegaze"}
    t_no = _track(genres=[], album_genres=[])
    assert compute_genre_match_score(t_no, hint, hint) == 0.0

    t_album = _track(genres=[], album_genres=["shoegaze"])
    assert compute_genre_match_score(t_album, hint, hint) > 0.0


def test_album_only_match_is_discounted_vs_primary():
    """Album-only match (0.75) scores below a primary track-genre match (1.0)."""
    hint = {"black metal"}
    primary = _track(genres=["black metal"])
    album_only = _track(genres=[], album_genres=["black metal"])
    assert compute_genre_match_score(album_only, hint, hint) < \
        compute_genre_match_score(primary, hint, hint)


def test_empty_hint_set_returns_zero():
    t = _track(genres=["rock"], album_genres=["rock"])
    assert compute_genre_match_score(t, set(), set()) == 0.0
