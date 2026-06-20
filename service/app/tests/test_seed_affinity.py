"""P-SEED / P-FOCUS — strong artist seeds + focused-mode arc flattening."""
from app.trajectory.candidates import (
    SeedExpansion,
    compute_seed_affinity_score,
    get_adaptive_weights,
)
from app.trajectory.intent import ArcType, GenreMode, PlaylistIntent, detect_focused


def _track(**kw):
    base = dict(
        id="t1", title="x", artist_name="A", artist_id="a1",
        album_name="al", album_id="alb1", year=2000, duration_ms=200000,
    )
    base.update(kw)
    from app.trajectory.candidates import CandidateTrack
    return CandidateTrack(**base)


def _intent(**kw):
    base = dict(raw_prompt="x", prompt_embedding=[])
    base.update(kw)
    return PlaylistIntent(**base)


# --- detect_focused ---------------------------------------------------------

def test_seeds_with_exclusivity_focused():
    # The war-metal case: named bands + "exclusively".
    assert detect_focused(
        "war metal exclusively. Blasphemy, Conqueror", ["war metal"], ["Blasphemy"], GenreMode.BALANCED
    ) is True


def test_exclusivity_word_is_focused():
    assert detect_focused("war metal exclusively", ["war metal"], [], GenreMode.BALANCED) is True


def test_strict_mode_is_focused():
    assert detect_focused("thrash", ["thrash metal"], [], GenreMode.STRICT) is True


def test_reference_artists_with_arc_not_focused():
    # "Think X, flowing into Y, closing with Z" names reference artists but wants
    # an arc — must NOT flatten (regression guard for the eval suite).
    assert detect_focused(
        "post-punk flowing into Bauhaus, closing with desolate goth",
        ["post-punk", "gothic rock"], ["Bauhaus", "Joy Division"], GenreMode.BALANCED,
    ) is False


def test_genuine_arc_is_not_focused():
    assert detect_focused(
        "build from ambient to crushing doom", ["ambient", "doom metal"], [], GenreMode.BALANCED
    ) is False


def test_no_genre_no_seed_not_focused():
    assert detect_focused("something moody", [], [], GenreMode.BALANCED) is False


# --- focused flattening in adaptive weights ---------------------------------

def test_focused_steady_flattens_trajectory():
    # No-arc focused prompt (STEADY → arc_strength 0): full flatten.
    base = _intent(genre_hints=["war metal"], genre_confidence=1.0,
                   arc_type=ArcType.STEADY, focused=False)
    foc = _intent(genre_hints=["war metal"], genre_confidence=1.0,
                  arc_type=ArcType.STEADY, focused=True)
    wb, wf = get_adaptive_weights(base), get_adaptive_weights(foc)
    assert wf["trajectory"] < wb["trajectory"]
    assert wf["genre"] > wb["genre"]
    assert abs(sum(wf.values()) - 1.0) < 1e-6  # redistribution preserves the sum


def test_strong_arc_focused_barely_flattens():
    # A genuine arc request that happens to be focused keeps most of its arc:
    # flattening is scaled by (1 - arc_strength).
    base = _intent(genre_hints=["doom metal"], genre_confidence=1.0,
                   arc_type=ArcType.PEAK, arc_confidence=0.9, focused=False)
    foc = _intent(genre_hints=["doom metal"], genre_confidence=1.0,
                  arc_type=ArcType.PEAK, arc_confidence=0.9, focused=True)
    wb, wf = get_adaptive_weights(base), get_adaptive_weights(foc)
    # <=15% of trajectory mass moved at arc_strength 0.9.
    assert (wb["trajectory"] - wf["trajectory"]) / wb["trajectory"] < 0.15


# --- seed affinity ----------------------------------------------------------

def _exp():
    return SeedExpansion(
        seed_artist_ids=frozenset({"seed1"}),
        specific_tags=frozenset({"war metal"}),
        neighbor_artist_ids=frozenset({"seed1", "nb1"}),
    )


def test_named_seed_artist_scores_full():
    assert compute_seed_affinity_score(_track(artist_id="seed1"), _exp()) == 1.0


def test_tag_neighbor_scores_partial():
    assert compute_seed_affinity_score(_track(artist_id="nb1"), _exp()) == 0.6


def test_unrelated_artist_scores_zero():
    assert compute_seed_affinity_score(_track(artist_id="other"), _exp()) == 0.0


def test_tag_corroboration_bonus():
    # Neighbor whose own genres carry the seed-specific tag gets a bonus.
    s = compute_seed_affinity_score(_track(artist_id="nb1", genres=["War Metal"]), _exp())
    assert s > 0.6


def test_no_expansion_is_noop():
    empty = SeedExpansion(frozenset(), frozenset(), frozenset())
    assert compute_seed_affinity_score(_track(artist_id="seed1"), empty) == 0.0
