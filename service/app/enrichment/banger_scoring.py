"""Pure scoring math for banger-factor v2. No I/O, no DB — unit-testable.

See docs/superpowers/specs/2026-06-11-banger-factor-v2-design.md.
"""
import bisect

# Genres for which valence must NOT penalize the sonic score.
DARK_GENRES = ("metal", "doom", "industrial", "darkwave", "goth", "noise")


def _clamp01(x) -> float:
    if x is None:
        return 0.0
    return max(0.0, min(1.0, float(x)))


def tempo_score(bpm) -> float:
    """1.0 across the 90-130 BPM banger zone; linear falloff to 0 at 70 and 180."""
    if not bpm or bpm <= 0:
        return 0.0
    if 90 <= bpm <= 130:
        return 1.0
    if bpm < 90:
        if bpm <= 70:
            return 0.0
        return (bpm - 70) / 20.0          # 70..90 -> 0..1
    if bpm >= 180:
        return 0.0
    return (180 - bpm) / 50.0             # 130..180 -> 1..0


def energy_proxy(loudness_norm, onset_rate_norm, pulse_clarity) -> float:
    """No literal energy column — derive from loudness/onset/pulse."""
    return _clamp01(
        0.5 * _clamp01(loudness_norm)
        + 0.3 * _clamp01(onset_rate_norm)
        + 0.2 * _clamp01(pulse_clarity)
    )


def is_dark_genre(tags) -> bool:
    """True if any tag substring-matches a DARK_GENRES entry (case-insensitive)."""
    for t in tags or ():
        tl = str(t).lower()
        if any(g in tl for g in DARK_GENRES):
            return True
    return False
