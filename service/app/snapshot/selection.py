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


def classic_bonus(year: int | None, anchor_year: int, ref_year: int) -> float:
    """Slight bias toward OG/classic releases: older effective_year → higher [0,1].

    Linear from `ref_year` (→0) back to `anchor_year` (→1), clamped. Unknown year
    is neutral (0.5) so missing-date tracks are neither rewarded nor punished.
    """
    if year is None:
        return 0.5
    if ref_year <= anchor_year:
        return 0.5
    return max(0.0, min(1.0, (ref_year - year) / (ref_year - anchor_year)))


def carries_target_genre(track: CandidateTrack, terms: set[str]) -> bool:
    """True if the track carries any precise target term in its file genres,
    album tags, or Last.fm artist tags (substring-tolerant, case-insensitive).

    This is the purist/strict gate: a track that merely shares the broad family
    (via genre expansion) but lacks the actual tag does NOT qualify.
    """
    if not terms:
        return True
    tags: list[str] = []
    tags.extend(g.lower() for g in (track.genres or []))
    tags.extend(g.lower() for g in (track.album_genres or []))
    tags.extend(k.lower() for k in (track.artist_tags or {}))
    for term in terms:
        for tag in tags:
            if term == tag or term in tag or tag in term:
                return True
    return False


def compute_snapshot_scores(
    tracks: list[CandidateTrack],
    base_darkness: float,
    mood_weight: float,
    floor: float,
    *,
    w_relevance: float = 0.30,
    w_legitimacy: float = 0.30,
    w_banger: float = 0.25,
    w_classic: float = 0.15,
    nonstudio_factor: float = 0.25,
    prefer_live: bool = False,
    classic_anchor_year: int = 1970,
    classic_ref_year: int = 2025,
) -> list[CandidateTrack]:
    """Set .snapshot_score from a weighted quality blend; drop below floor.

    score = (w_relevance*relevance + w_legitimacy*MA_legitimacy + w_banger*banger
             + w_classic*classic) * studio_factor

    - The floor is applied to RELEVANCE (niche fit), not the blended score, so a
      high-quality track that is off-niche is still excluded (strict floor).
    - Studio ALWAYS wins: live/demo/remix get a steep multiplicative demotion
      (`nonstudio_factor`), so they only surface when no studio version competes.
      Lifted when the prompt explicitly prefers live recordings.
    """
    kept: list[CandidateTrack] = []
    for t in tracks:
        r = relevance(t, base_darkness, mood_weight)
        if r < floor:
            continue
        legit = max(0.0, min(1.0, t.album_legitimacy_score))
        banger = max(0.0, min(1.0, t.banger_score))
        classic = classic_bonus(t.effective_year, classic_anchor_year, classic_ref_year)
        base = (
            w_relevance * r
            + w_legitimacy * legit
            + w_banger * banger
            + w_classic * classic
        )
        is_studio = t.version_type == "studio"
        studio_factor = 1.0 if (prefer_live or is_studio) else nonstudio_factor
        t.snapshot_score = base * studio_factor
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


def apply_soft_cap(
    by_artist: dict[str, list[CandidateTrack]],
    cap: int,
) -> list[CandidateTrack]:
    """Flatten per-artist picks to <= cap, strongest artists first.

    Artists are ranked by their best track's snapshot_score; we take whole
    artist blocks until the cap, allowing a partial final artist. Returns all
    picks when the total is under the cap (the list IS the snapshot).
    """
    ranked_artists = sorted(
        by_artist.items(),
        key=lambda kv: max((t.snapshot_score for t in kv[1]), default=0.0),
        reverse=True,
    )
    out: list[CandidateTrack] = []
    for _artist, picks in ranked_artists:
        if len(out) >= cap:
            break
        ordered = sorted(picks, key=lambda t: t.snapshot_score, reverse=True)
        for t in ordered:
            if len(out) >= cap:
                break
            out.append(t)
    return out


def shuffle_no_adjacent_artist(
    tracks: list[CandidateTrack],
    seed: int,
) -> list[CandidateTrack]:
    """Random order with no two same-artist tracks adjacent (seeded/deterministic).

    Greedy: repeatedly place the most-remaining artist that isn't the previous
    artist. This always succeeds when no artist holds a strict majority; snapshot
    selections (<= max_per_artist per artist over many artists) satisfy that.
    """
    import random

    rng = random.Random(seed)
    buckets: dict[str | None, list[CandidateTrack]] = {}
    for t in tracks:
        buckets.setdefault(t.artist_id, []).append(t)
    for b in buckets.values():
        rng.shuffle(b)

    out: list[CandidateTrack] = []
    prev_artist: object = object()  # sentinel != any artist_id
    while any(buckets.values()):
        # candidate artists with tracks left, excluding the previous one
        avail = [a for a, b in buckets.items() if b and a != prev_artist]
        if not avail:
            # only the previous artist remains — unavoidable; place it
            avail = [a for a, b in buckets.items() if b]
        # pick the artist with the most remaining (ties broken randomly)
        rng.shuffle(avail)
        artist = max(avail, key=lambda a: len(buckets[a]))
        out.append(buckets[artist].pop())
        prev_artist = artist
    return out
