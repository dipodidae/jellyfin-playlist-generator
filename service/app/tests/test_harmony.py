"""Tests for harmonic compatibility (P3, C4) — pure, no DB."""
import pytest

from app.trajectory.harmony import NEUTRAL, harmonic_compat, parse_key


def test_parse_key_sharps_flats_and_garbage():
    assert parse_key("C") == 0
    assert parse_key("d#") == 3
    assert parse_key("Eb") == 3        # enharmonic with D#
    assert parse_key("Bb") == 10
    assert parse_key("E major") == 4   # tolerates trailing mode
    assert parse_key("") is None
    assert parse_key(None) is None
    assert parse_key("zzz") is None


def test_same_key_is_max():
    assert harmonic_compat("E", "E") == pytest.approx(1.0)


def test_perfect_fifth_is_high():
    # C -> G is one step on the circle of fifths.
    assert harmonic_compat("C", "G") == pytest.approx(1.0 - (1 / 6) * 0.6)
    # symmetric
    assert harmonic_compat("G", "C") == harmonic_compat("C", "G")


def test_tritone_is_lowest():
    # C -> F# is a tritone: max circle-of-fifths distance (6).
    assert harmonic_compat("C", "F#") == pytest.approx(0.4)


def test_monotonic_decrease_with_distance():
    seq = [
        harmonic_compat("C", "C"),   # 0
        harmonic_compat("C", "G"),   # 1
        harmonic_compat("C", "D"),   # 2
        harmonic_compat("C", "A"),   # 3
        harmonic_compat("C", "E"),   # 4
        harmonic_compat("C", "B"),   # 5
        harmonic_compat("C", "F#"),  # 6
    ]
    assert seq == sorted(seq, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in seq)


def test_missing_key_is_neutral():
    assert harmonic_compat(None, "C") == NEUTRAL
    assert harmonic_compat("C", "") == NEUTRAL
    assert harmonic_compat("zzz", "C") == NEUTRAL


def test_enharmonic_equivalence():
    # D# and Eb are the same pitch class -> identical compatibility profile.
    assert harmonic_compat("D#", "G") == harmonic_compat("Eb", "G")
