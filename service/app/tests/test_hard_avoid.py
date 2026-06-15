"""PARSE_AUDIT P5 — reliable hard exclusions for strong avoids."""
from types import SimpleNamespace

from app.trajectory.candidates import compute_genre_exclusion
from app.trajectory.intent import extract_avoid_keywords, extract_hard_avoid_keywords


def test_hard_avoid_extracts_strong_forms_only():
    hard = extract_hard_avoid_keywords("dark synth, no metal and without jazz, not too bright")
    assert "metal" in hard
    assert "jazz" in hard
    # "not too X" is a soft preference — must NOT become a hard avoid.
    assert "bright" not in hard


def test_soft_avoid_still_captures_not_too():
    soft = extract_avoid_keywords("not too bright")
    assert "bright" in soft


def _track(genres=None, album_genres=None):
    return SimpleNamespace(genres=genres or [], album_genres=album_genres)


def test_genre_exclusion_matches_family_token():
    # "no metal" excludes any *-metal track via token match.
    assert compute_genre_exclusion(_track(["thrash metal"]), ["metal"]) is True
    assert compute_genre_exclusion(_track(["black metal"]), ["metal"]) is True


def test_genre_exclusion_matches_exact_genre():
    assert compute_genre_exclusion(_track(["jazz"]), ["jazz"]) is True


def test_genre_exclusion_unrelated_avoid_does_not_match():
    # An avoid term with no genre overlap never hard-excludes.
    assert compute_genre_exclusion(_track(["coldwave"]), ["happy"]) is False
    assert compute_genre_exclusion(_track(["jazz"]), ["metal"]) is False


def test_genre_exclusion_no_genres():
    assert compute_genre_exclusion(_track([]), ["metal"]) is False


def test_genre_exclusion_empty_avoids():
    assert compute_genre_exclusion(_track(["jazz"]), []) is False
