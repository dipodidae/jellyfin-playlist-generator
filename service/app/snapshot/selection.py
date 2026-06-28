"""Pure selection primitives for snapshot mode.

No I/O. Operates on already-scored CandidateTrack lists so each function is
unit-testable in isolation. Snapshot mode wants BREADTH across artists, with a
banger + strong deep cuts per artist, not a trajectory.
"""

from __future__ import annotations

import math

from app.trajectory.candidates import CandidateTrack


def relevance(track: CandidateTrack, base_darkness: float, mood_weight: float) -> float:
    """Niche fit in [0,1]: genre match, nudged by mood (darkness) proximity.

    mood_weight blends the two; with mood_weight=0.3 a perfect genre match with a
    far-off mood still scores ~0.7, but a closer mood lifts it toward 1.0.
    """
    gm = max(0.0, min(1.0, track.genre_match_score))
    mood_prox = 1.0 - abs(track.darkness - base_darkness)  # 1.0 = exact match
    mw = max(0.0, min(1.0, mood_weight))
    return (1.0 - mw) * gm + mw * (gm * mood_prox)


def compute_snapshot_scores(
    tracks: list[CandidateTrack],
    base_darkness: float,
    mood_weight: float,
    floor: float,
) -> list[CandidateTrack]:
    """Set .snapshot_score = 0.5*relevance + 0.5*curation; drop below floor.

    The floor is applied to RELEVANCE (niche fit), not the blended score, so a
    high-curation track that is off-niche is still excluded (strict floor).
    """
    kept: list[CandidateTrack] = []
    for t in tracks:
        r = relevance(t, base_darkness, mood_weight)
        if r < floor:
            continue
        t.snapshot_score = 0.5 * r + 0.5 * max(0.0, min(1.0, t.curation_score))
        kept.append(t)
    return kept


def is_banger(
    track: CandidateTrack,
    artist_tracks: list[CandidateTrack],
    percentile: float,
) -> bool:
    """True if track.banger_score is at/above the `percentile`-th percentile of
    its artist's popularity distribution.

    A lone track (single-element artist) with any positive banger_score counts.
    """
    scores = sorted(t.banger_score for t in artist_tracks)
    if not scores:
        return False
    if len(scores) == 1:
        return track.banger_score > 0.0
    # Round the percentile rank UP so e.g. percentile=0.6 over [0.1, 0.9] marks
    # only the 0.9 as a banger (top of the distribution), not both.
    idx = min(len(scores) - 1, math.ceil(percentile * (len(scores) - 1)))
    threshold = scores[idx]
    return track.banger_score >= threshold and track.banger_score > 0.0


def select_artist_tracks(
    artist_tracks: list[CandidateTrack],
    min_n: int,
    max_n: int,
    album_cap: int,
    banger_percentile: float,
) -> list[CandidateTrack]:
    """Pick min_n..max_n tracks for one artist: banger + best deep cuts.

    Ranks by snapshot_score, guarantees the artist's top banger is included, and
    caps how many come from any single album. Returns fewer than min_n only when
    the artist simply has fewer qualifying tracks.
    """
    ranked = sorted(artist_tracks, key=lambda t: t.snapshot_score, reverse=True)
    picked: list[CandidateTrack] = []
    per_album: dict[str | None, int] = {}

    def _try_add(track: CandidateTrack) -> bool:
        if track in picked:
            return False
        if per_album.get(track.album_id, 0) >= album_cap:
            return False
        picked.append(track)
        per_album[track.album_id] = per_album.get(track.album_id, 0) + 1
        return True

    # 1. Guarantee the top banger (by banger_score) if one qualifies.
    bangers = sorted(
        (t for t in ranked if is_banger(t, artist_tracks, banger_percentile)),
        key=lambda t: t.banger_score, reverse=True,
    )
    if bangers:
        _try_add(bangers[0])

    # 2. Fill remaining slots with the highest snapshot_score tracks (deep cuts).
    for t in ranked:
        if len(picked) >= max_n:
            break
        _try_add(t)

    return picked[:max_n]
