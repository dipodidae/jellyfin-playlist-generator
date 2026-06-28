"""Snapshot composer: breadth-across-artists representative cross-section.

Reuses intent parsing and the flat candidate-scoring helpers, but deliberately
bypasses the trajectory engine (no position pools, no beam search). Returns the
same PlaylistResult shape so the route's title/save/export path is unchanged.
"""

from __future__ import annotations

import logging
import time

from app.config import settings
from app.observability import log_generation, update_track_usage
from app.snapshot.selection import (
    apply_soft_cap,
    compute_snapshot_scores,
    select_artist_tracks,
    shuffle_no_adjacent_artist,
)
from app.trajectory.candidates import (
    CandidateTrack,
    _attach_artist_tags,
    _fetch_candidates_by_ids,
    _normalize_album_legitimacy,
    compute_genre_exclusion,
    compute_genre_match_score,
    derive_niche_hints,
    keyword_search,
    semantic_search,
)
from app.trajectory.composer_v4 import PlaylistResult
from app.trajectory.intent import get_primary_genre_hints, parse_prompt

logger = logging.getLogger(__name__)


def _gather_pool(intent, limit: int) -> list[CandidateTrack]:
    """Build one flat, uniformly-enriched candidate pool for the niche."""
    pool: dict[str, CandidateTrack] = {}
    for c in semantic_search(intent.prompt_embedding, limit=limit,
                             year_range=intent.year_range):
        pool[c.id] = c
    # Supplement with keyword hits; hydrate keyword-only ids for uniform fields.
    kw = keyword_search(intent.raw_prompt, limit=limit, genre_hints=intent.genre_hints)
    missing = [c.id for c in kw if c.id not in pool]
    if missing:
        for c in _fetch_candidates_by_ids(missing):
            pool[c.id] = c
    return list(pool.values())


def compose_snapshot(prompt: str, soft_cap: int | None = None) -> PlaylistResult:
    """Compose an archival snapshot playlist (breadth across artists)."""
    start = time.time()
    cap = max(20, soft_cap or settings.snapshot_soft_cap)

    intent = parse_prompt(prompt)

    pool = _gather_pool(intent, settings.snapshot_pool_limit)
    if not pool:
        return PlaylistResult(
            tracks=[], intent=intent,
            metrics={"mode": "snapshot", "error": "no_candidates"},
            generation_time_ms=int((time.time() - start) * 1000),
        )

    # Uniform enrichment (mirrors generate_position_pools' post-assembly steps).
    _normalize_album_legitimacy(pool)
    _attach_artist_tags(pool)

    # Niche-aware genre match → relevance input.
    niche_hints, demote_families = derive_niche_hints(intent.genre_hints_raw)
    hint_set = {h.lower() for h in intent.genre_hints}
    primary = get_primary_genre_hints(intent.genre_hints)
    hard_avoids = intent.hard_avoid_keywords

    # Year range is a HARD cut. semantic_search applies it in SQL, but the
    # keyword-supplement path (_fetch_candidates_by_ids) does not — so enforce it
    # here over the merged pool. Mirrors the arc engine's SQL semantics, where a
    # NULL/unknown year fails the bound and is excluded for an explicit era.
    yr0, yr1 = intent.year_range
    has_year_filter = yr0 is not None or yr1 is not None

    def _year_ok(t: CandidateTrack) -> bool:
        if not has_year_filter:
            return True
        ey = t.effective_year
        if ey is None:
            return False
        return (yr0 is None or ey >= yr0) and (yr1 is None or ey <= yr1)

    survivors: list[CandidateTrack] = []
    for t in pool:
        if hard_avoids and compute_genre_exclusion(t, hard_avoids):
            continue
        if not _year_ok(t):
            continue
        t.genre_match_score = compute_genre_match_score(
            t, hint_set, primary, niche_hints, demote_families,
        )
        survivors.append(t)

    qualifying = compute_snapshot_scores(
        survivors,
        base_darkness=intent.base_darkness,
        mood_weight=settings.snapshot_mood_weight,
        floor=settings.snapshot_relevance_floor,
    )

    # Bucket by artist; pick banger + deep cuts per artist; drop artists whose
    # best track fell below the floor (they are simply absent from `qualifying`).
    by_artist: dict[str, list[CandidateTrack]] = {}
    for t in qualifying:
        if t.artist_id:
            by_artist.setdefault(t.artist_id, []).append(t)

    selected_by_artist: dict[str, list[CandidateTrack]] = {}
    for artist_id, tracks in by_artist.items():
        picks = select_artist_tracks(
            tracks,
            min_n=settings.snapshot_min_per_artist,
            max_n=settings.snapshot_max_per_artist,
            album_cap=settings.snapshot_album_cap,
            banger_percentile=settings.snapshot_banger_percentile,
        )
        if picks:
            selected_by_artist[artist_id] = picks

    capped = apply_soft_cap(selected_by_artist, cap)

    # Deterministic-but-fresh order: seed off the prompt + count so re-running the
    # same prompt within a process is stable, but prompts/sizes/restarts vary.
    seed = (abs(hash(intent.raw_prompt)) % 1_000_000) + len(capped)
    ordered = shuffle_no_adjacent_artist(capped, seed=seed)

    banger_count = sum(1 for t in ordered if t.banger_score >= 0.5)
    metrics = {
        "mode": "snapshot",
        "qualifying_tracks": len(qualifying),
        "distinct_artists": len({t.artist_id for t in ordered}),
        "banger_count": banger_count,
        "deep_cut_count": len(ordered) - banger_count,
        "soft_cap": cap,
        "niche_floor": settings.snapshot_relevance_floor,
        "pool_size": len(pool),
    }
    gen_ms = int((time.time() - start) * 1000)
    metrics["generation_time_ms"] = gen_ms

    log_generation(
        prompt=prompt,
        arc_type="snapshot",
        playlist_length=len(ordered),
        generation_time_ms=gen_ms,
        metrics=metrics,
    )
    update_track_usage([t.id for t in ordered])

    logger.info(
        f"Snapshot compose: '{prompt[:40]}' → {len(ordered)} tracks, "
        f"{metrics['distinct_artists']} artists in {gen_ms}ms"
    )
    return PlaylistResult(tracks=ordered, intent=intent, metrics=metrics,
                          generation_time_ms=gen_ms)
