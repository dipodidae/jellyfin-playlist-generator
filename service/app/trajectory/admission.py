"""Pure admissibility predicate for the candidate gate.

Stdlib-only so it is unit-testable without app dependencies.
"""
from __future__ import annotations

# A track below the semantic floor is still admitted if it is a strong
# match for a primary genre hint — this lets the genre/tag secondary pools
# (which carry a low baseline semantic_score) actually contribute.
STRONG_GENRE_THRESHOLD = 0.50


def is_admissible(
    *,
    semantic_score: float,
    semantic_floor: float,
    genre_match_score: float,
    admissibility_score: float,
    admissibility_floor: float,
    negative_constraint_penalty: float,
    neg_constraint_ceiling: float,
    has_genre_hints: bool,
    strong_genre_threshold: float = STRONG_GENRE_THRESHOLD,
) -> bool:
    """Return True if a candidate passes the admissibility gate."""
    if admissibility_score < admissibility_floor:
        return False
    if negative_constraint_penalty >= neg_constraint_ceiling:
        return False
    if semantic_score >= semantic_floor:
        return True
    if has_genre_hints and genre_match_score >= strong_genre_threshold:
        return True
    return False
