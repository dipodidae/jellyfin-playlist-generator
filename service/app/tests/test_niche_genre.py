"""P-NICHE — niche/microgenre genre discrimination via tags + broad-parent demotion."""
from app.trajectory.candidates import (
    CandidateTrack,
    compute_genre_match_score,
    derive_niche_hints,
)


def _track(genres=None, artist_tags=None):
    return CandidateTrack(
        id="t", title="x", artist_name="A", artist_id="a", album_name="al",
        album_id="alb", year=2000, duration_ms=200000,
        genres=genres or [], artist_tags=artist_tags or {},
    )


# --- derive_niche_hints -----------------------------------------------------

def test_tag_only_term_is_niche():
    # "war metal" isn't in the built-in taxonomy → niche via Last.fm tags.
    niche, demote = derive_niche_hints(["war metal"])
    assert "war metal" in niche
    assert demote == set()


def test_subgenre_demotes_broad_parent():
    niche, demote = derive_niche_hints(["bestial black metal"])
    assert "bestial black metal" in niche
    assert "black metal" in demote  # parent suppressed


def test_family_level_is_not_niche():
    # Family-level requests keep the baseline (no niche regime).
    assert derive_niche_hints(["thrash metal"]) == (set(), set())
    assert derive_niche_hints(["darkwave"]) == (set(), set())


def test_broad_genre_ignored():
    assert derive_niche_hints(["metal"]) == (set(), set())


# --- compute_genre_match_score, niche regime --------------------------------

HINTS = {"war metal", "black metal"}  # expanded hint_set (incl. broad sibling)
NICHE = {"war metal"}


def test_niche_genre_tag_full_credit():
    # File genre carries the niche → authoritative 1.0.
    t = _track(genres=["Black Metal", "War Metal"])
    assert compute_genre_match_score(t, HINTS, HINTS, NICHE, set()) == 1.0


def test_niche_lastfm_tag_strong_credit():
    # Niche lives only in Last.fm artist tags → near-authoritative, weight-scaled.
    t = _track(genres=["Black Metal"], artist_tags={"war metal": 56.0, "black metal": 100.0})
    s = compute_genre_match_score(t, HINTS, HINTS, NICHE, set())
    assert 0.75 < s <= 1.0


def test_broad_family_only_is_demoted():
    # Generic black metal (no war-metal evidence) gets only weak 0.2.
    t = _track(genres=["Black Metal"], artist_tags={"black metal": 100.0, "melodic black metal": 80.0})
    assert compute_genre_match_score(t, HINTS, HINTS, NICHE, set()) == 0.2


def test_unrelated_genre_zero():
    t = _track(genres=["Jazz"], artist_tags={"jazz": 100.0})
    assert compute_genre_match_score(t, HINTS, HINTS, NICHE, set()) == 0.0


def test_weak_lastfm_tag_below_threshold_not_full():
    # A war-metal tag below the weight floor doesn't earn full niche credit.
    t = _track(genres=["Black Metal"], artist_tags={"war metal": 10.0, "black metal": 100.0})
    assert compute_genre_match_score(t, HINTS, HINTS, NICHE, set()) == 0.2


def test_non_niche_regime_unchanged():
    # With no niche_hints, broad family still scores full (baseline preserved).
    t = _track(genres=["Black Metal"])
    assert compute_genre_match_score(t, {"black metal"}, {"black metal"}) == 1.0
