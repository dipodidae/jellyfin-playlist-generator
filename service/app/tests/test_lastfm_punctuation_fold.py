"""Tests for the ASCII punctuation fold on Last.fm lookups.

Last.fm matches artist/album/track names as literal strings. This library is
tagged MusicBrainz/Picard-style, so names carry typographic punctuation that
Last.fm's catalogue does not use, and an exact lookup returns nothing --
indistinguishable from "Last.fm has no data for this". Measured 2026-09-16,
five for five: folding the name turned 0 tags into 6-10.

All pure; no network.
"""

from app.ingestion.lastfm import _folded_variant, fold_punctuation

# --- the folds that were actually costing data ------------------------------


def test_right_single_quote_becomes_an_apostrophe():
    assert fold_punctuation("Script for a Jester’s Tear") == "Script for a Jester's Tear"


def test_ellipsis_becomes_three_dots():
    assert (
        fold_punctuation("The Four Instructive Tales …of Decomposition")
        == "The Four Instructive Tales ...of Decomposition"
    )


def test_unicode_hyphen_becomes_ascii_hyphen():
    assert fold_punctuation("a‐ha") == "a-ha"
    assert fold_punctuation("Gil Scott‐Heron") == "Gil Scott-Heron"


def test_en_and_em_dashes_fold_too():
    assert fold_punctuation("Godspeed You—Black Emperor") == "Godspeed You-Black Emperor"
    assert fold_punctuation("1979–1983") == "1979-1983"


def test_zero_width_and_nbsp_are_removed_or_normalised():
    assert fold_punctuation("Sun​n O)))") == "Sunn O)))"
    assert fold_punctuation("Deep Purple") == "Deep Purple"


# --- what must NOT be folded ------------------------------------------------


def test_diacritics_are_preserved():
    """Last.fm really does hold these under their accented names."""
    for name in ("Motörhead", "Sigur Rós", "Blåhall", "Crüxshadows"):
        assert fold_punctuation(name) == name


def test_ascii_names_are_untouched():
    assert fold_punctuation("Judas Priest") == "Judas Priest"
    assert fold_punctuation("AC/DC") == "AC/DC"


def test_empty_and_none_are_safe():
    assert fold_punctuation("") == ""
    assert fold_punctuation(None) == ""


# --- the retry gate ---------------------------------------------------------


def test_no_retry_when_folding_changes_nothing():
    """An identical second query is a wasted Last.fm call, so it is not made."""
    assert _folded_variant("Judas Priest", "Painkiller") is None
    assert _folded_variant("Metallica") is None


def test_retry_when_folding_changes_something():
    assert _folded_variant("Marillion", "Script for a Jester’s Tear") == (
        "Marillion",
        "Script for a Jester's Tear",
    )


def test_retry_gate_looks_at_every_name_not_just_the_first():
    """The album title is usually what carries the punctuation, not the artist."""
    assert _folded_variant("Austere", "Bleak…") == ("Austere", "Bleak...")
    assert _folded_variant("a‐ha", "Cast in Steel") == ("a-ha", "Cast in Steel")
