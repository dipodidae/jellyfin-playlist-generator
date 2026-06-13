"""Harmonic compatibility between track keys (P3, C4).

The stored ``key_estimate`` is a bare tonic pitch class ("E", "D#", ...) with no
major/minor mode, so compatibility is computed as circle-of-fifths distance
between tonal centers: tonics a perfect fifth/fourth apart blend smoothly,
tritone-distant tonics clash. Pure functions — no I/O.
"""

_NOTE_TO_PC = {
    "c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3, "e": 4, "fb": 4,
    "e#": 5, "f": 5, "f#": 6, "gb": 6, "g": 7, "g#": 8, "ab": 8, "a": 9,
    "a#": 10, "bb": 10, "b": 11, "cb": 11,
}

# Neutral score when a key is missing/unparseable: must not skew continuity.
NEUTRAL = 0.5


def parse_key(s) -> "int | None":
    """Parse a stored key string to a pitch class 0-11, or None.

    Accepts just the tonic ("E", "D#", "Bb"); ignores any trailing mode words
    ("E major") defensively in case the data format changes.
    """
    if not s:
        return None
    token = str(s).strip().lower().split()[0] if str(s).strip() else ""
    return _NOTE_TO_PC.get(token)


def _cof_distance(pc_a: int, pc_b: int) -> int:
    """Circular distance (0-6) between two pitch classes on the circle of fifths.

    The circle-of-fifths index of a pitch class is (pc * 7) mod 12 (7 is its own
    inverse mod 12). Distance is the shorter way around the 12-step circle.
    """
    ia = (pc_a * 7) % 12
    ib = (pc_b * 7) % 12
    d = abs(ia - ib)
    return min(d, 12 - d)


def harmonic_compat(key_a, key_b) -> float:
    """Compatibility in [0,1] between two key strings.

    1.0 for the same tonic, tapering with circle-of-fifths distance to ~0.4 at a
    tritone. NEUTRAL (0.5) when either key is missing/unparseable so the term
    neither rewards nor penalizes unknown keys.
    """
    pa = parse_key(key_a)
    pb = parse_key(key_b)
    if pa is None or pb is None:
        return NEUTRAL
    dist = _cof_distance(pa, pb)  # 0..6
    return 1.0 - (dist / 6.0) * 0.6
