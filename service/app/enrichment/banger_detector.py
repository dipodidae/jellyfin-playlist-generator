"""Banger detection — composite score from data the stack already holds.

Blends three signal groups (weights renormalized over whichever are present):
  - popularity (0.45): within-artist log(playcount) rank + global log(listeners)
    percentile, from lastfm_stats.
  - sonic (0.35): librosa-derived energy/danceability/loudness/tempo/valence from
    track_audio_features, with valence dropped for dark genres (metal, doom,
    industrial, darkwave, goth, noise).
  - replay (0.20): percentile of log(playcount/listeners) — repeat-play ratio.

All scoring math lives in the pure, unit-tested banger_scoring module; this file
is the DB orchestration (query + persist to track_banger_flags). No external API
calls. See docs/superpowers/specs/2026-06-11-banger-factor-v2-design.md.
"""

import json
import logging
import math
from typing import Any

from app.database_pg import get_connection
from app.enrichment.banger_scoring import (
    composite_banger_score,
    confidence_score,
    energy_proxy,
    is_dark_genre,
    percentile_of,
    sonic_score,
)

logger = logging.getLogger(__name__)

# Minimum tracks per artist for within-artist ranking
_MIN_ARTIST_TRACKS = 5

# Percentile thresholds
_WITHIN_ARTIST_TOP_FRACTION = 0.20  # top 20% = strong banger signal
_GLOBAL_LISTENER_PERCENTILE = 0.80  # above 80th = signal


def _compute_banger_scores() -> list[dict[str, Any]]:
    """Compute banger scores for all tracks with Last.fm data.

    Returns list of dicts: track_id, banger_score, confidence, sources.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Fetch all tracks with Last.fm stats + primary artist + audio
            # features + genre tags. Tag names need a two-hop join
            # (track_lastfm_tags.tag_id -> lastfm_tags.name).
            cur.execute("""
                SELECT ls.track_id, ls.playcount, ls.listeners,
                       ta.artist_id, a.name as artist_name,
                       af.bpm, af.loudness_norm, af.onset_rate_norm,
                       af.pulse_clarity, af.danceability, af.valence,
                       COALESCE(
                           array_agg(DISTINCT lft.name)
                               FILTER (WHERE lft.name IS NOT NULL),
                           ARRAY[]::text[]
                       ) AS tags
                FROM lastfm_stats ls
                JOIN track_artists ta ON ls.track_id = ta.track_id AND ta.role = 'primary'
                JOIN artists a ON ta.artist_id = a.id
                LEFT JOIN track_audio_features af ON ls.track_id = af.track_id
                LEFT JOIN track_lastfm_tags tlt ON ls.track_id = tlt.track_id
                LEFT JOIN lastfm_tags lft ON tlt.tag_id = lft.id
                WHERE ls.playcount > 0 OR ls.listeners > 0
                GROUP BY ls.track_id, ls.playcount, ls.listeners, ta.artist_id,
                         a.name, af.bpm, af.loudness_norm, af.onset_rate_norm,
                         af.pulse_clarity, af.danceability, af.valence
            """)
            rows = cur.fetchall()

    if not rows:
        logger.warning("No Last.fm stats found — cannot compute banger scores")
        return []

    # Build data structures
    tracks = []
    artist_tracks: dict[str, list[dict]] = {}  # artist_id -> [track_data]
    all_listeners: list[float] = []

    for (track_id, playcount, listeners, artist_id, artist_name,
         bpm, loudness_norm, onset_rate_norm, pulse_clarity,
         danceability, valence, tags) in rows:
        # Audio features present only if the track has been analyzed. Any of
        # the core sonic inputs being non-null counts as "analyzed".
        has_audio = any(v is not None for v in (
            bpm, loudness_norm, onset_rate_norm, danceability, valence))
        td = {
            "track_id": str(track_id),
            "playcount": playcount or 0,
            "listeners": listeners or 0,
            "artist_id": str(artist_id),
            "artist_name": artist_name,
            "log_playcount": math.log1p(playcount or 0),
            "log_listeners": math.log1p(listeners or 0),
            "has_audio": has_audio,
            "bpm": bpm,
            "loudness_norm": loudness_norm,
            "onset_rate_norm": onset_rate_norm,
            "pulse_clarity": pulse_clarity,
            "danceability": danceability,
            "valence": valence,
            "tags": list(tags or []),
        }
        tracks.append(td)
        artist_tracks.setdefault(str(artist_id), []).append(td)
        if listeners and listeners > 0:
            all_listeners.append(math.log1p(listeners))

    # Compute global listener percentile threshold
    all_listeners.sort()
    n_listeners = len(all_listeners)
    if n_listeners > 0:
        p80_idx = int(n_listeners * _GLOBAL_LISTENER_PERCENTILE)
        global_p80_threshold = all_listeners[min(p80_idx, n_listeners - 1)]
    else:
        global_p80_threshold = float("inf")

    global_max_log_listeners = max(all_listeners) if all_listeners else 1.0

    # Replay signal: library-wide distribution of log1p(playcount/listeners),
    # used to percentile-normalize each track's repeat-play ratio.
    replay_log_sorted = sorted(
        math.log1p(t["playcount"] / t["listeners"])
        for t in tracks if t["listeners"] > 0
    )

    # Compute within-artist rankings
    artist_rankings: dict[str, dict[str, float]] = {}  # artist_id -> {track_id -> rank_score}
    for artist_id, atracks in artist_tracks.items():
        if len(atracks) < _MIN_ARTIST_TRACKS:
            continue  # fallback to global only for small catalogs

        # Sort by log_playcount descending
        sorted_tracks = sorted(atracks, key=lambda t: t["log_playcount"], reverse=True)
        n = len(sorted_tracks)

        rankings = {}
        for rank, t in enumerate(sorted_tracks):
            # Normalized rank score: 1.0 for #1, 0.0 for last
            rank_score = 1.0 - (rank / max(1, n - 1))
            rankings[t["track_id"]] = rank_score
        artist_rankings[artist_id] = rankings

    # Compute final scores
    results = []
    for t in tracks:
        sources = []
        within_artist_score = 0.0
        global_listener_score = 0.0
        has_artist_signal = False
        has_global_signal = False

        # Signal 1: within-artist rank
        if t["artist_id"] in artist_rankings:
            rank_score = artist_rankings[t["artist_id"]].get(t["track_id"], 0.0)
            within_artist_score = rank_score
            n_artist_tracks = len(artist_tracks[t["artist_id"]])
            top_threshold = 1.0 - _WITHIN_ARTIST_TOP_FRACTION
            has_artist_signal = rank_score >= top_threshold
            sources.append({
                "type": "lastfm_artist_rank",
                "value": round(rank_score, 3),
                "artist_tracks": n_artist_tracks,
            })
        else:
            # Small catalog — use global playcount as rough proxy
            if global_max_log_listeners > 0:
                within_artist_score = t["log_playcount"] / max(1.0, max(
                    td["log_playcount"] for td in tracks
                ))

        # Signal 2: global listener percentile
        if global_max_log_listeners > 0 and t["log_listeners"] > 0:
            # Percentile-style: what fraction of library this track exceeds
            below_count = sum(1 for ll in all_listeners if ll <= t["log_listeners"])
            global_listener_score = below_count / max(1, n_listeners)
            has_global_signal = t["log_listeners"] >= global_p80_threshold
            sources.append({
                "type": "lastfm_global_listeners",
                "value": round(global_listener_score, 3),
                "percentile": round(global_listener_score * 100, 1),
            })

        # Group 1: popularity (within-artist rank 0.60 + global percentile 0.40).
        # Always present here — every row in this query has Last.fm data.
        popularity = within_artist_score * 0.60 + global_listener_score * 0.40

        # Group 2: sonic profile (only when the track has been audio-analyzed).
        sonic = None
        if t["has_audio"]:
            dark = is_dark_genre(t["tags"])
            sonic = sonic_score(
                energy=energy_proxy(
                    t["loudness_norm"], t["onset_rate_norm"], t["pulse_clarity"]),
                danceability=t["danceability"],
                loudness_norm=t["loudness_norm"],
                bpm=t["bpm"],
                valence=t["valence"],
                dark=dark,
            )
            sources.append({
                "type": "sonic_audio",
                "value": round(sonic, 3),
                "valence_corrected": dark,
            })

        # Group 3: replay ratio (only when global listeners > 0).
        replay = None
        if t["listeners"] > 0:
            ratio = t["playcount"] / t["listeners"]
            replay = percentile_of(math.log1p(ratio), replay_log_sorted)
            sources.append({
                "type": "lastfm_replay_ratio",
                "value": round(replay, 3),
                "ratio": round(ratio, 2),
            })

        banger_score = composite_banger_score(
            popularity=popularity, sonic=sonic, replay=replay)

        n_groups = sum(x is not None for x in (popularity, sonic, replay))
        strong_signals = int(has_artist_signal) + int(has_global_signal)
        confidence = confidence_score(n_groups, strong_signals, banger_score)

        results.append({
            "track_id": t["track_id"],
            "banger_score": round(banger_score, 4),
            "confidence": round(confidence, 4),
            "sources": sources,
        })

    return results


def _save_banger_flags(results: list[dict[str, Any]], force: bool = False) -> int:
    """Persist banger flags to database. Returns count of rows written."""
    if not results:
        return 0

    saved = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for r in results:
                if force:
                    cur.execute(
                        """
                        INSERT INTO track_banger_flags
                            (track_id, banger_score, confidence, sources, computed_at)
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (track_id) DO UPDATE SET
                            banger_score = excluded.banger_score,
                            confidence = excluded.confidence,
                            sources = excluded.sources,
                            computed_at = excluded.computed_at
                        """,
                        [r["track_id"], r["banger_score"], r["confidence"],
                         json.dumps(r["sources"])],
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO track_banger_flags
                            (track_id, banger_score, confidence, sources, computed_at)
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (track_id) DO NOTHING
                        """,
                        [r["track_id"], r["banger_score"], r["confidence"],
                         json.dumps(r["sources"])],
                    )
                saved += 1
    return saved


async def compute_banger_flags(
    force: bool = False,
    progress_callback: Any = None,
) -> dict[str, int]:
    """Compute and persist banger flags for all tracks with Last.fm data.

    Args:
        force: Recompute for tracks that already have flags.
        progress_callback: Optional (current, total, message) callback.

    Returns:
        Stats dict with counts.
    """
    if progress_callback:
        progress_callback(0, 1, "Computing banger scores from Last.fm data...")

    results = _compute_banger_scores()

    if not results:
        if progress_callback:
            progress_callback(1, 1, "No Last.fm data available for banger detection")
        return {"tracks_scored": 0, "tracks_saved": 0}

    # Filter to only tracks that need updating (unless force)
    if not force:
        existing_ids = set()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT track_id FROM track_banger_flags")
                existing_ids = {str(row[0]) for row in cur.fetchall()}
        results = [r for r in results if r["track_id"] not in existing_ids]

    total_scored = len(results)

    if progress_callback:
        progress_callback(0, total_scored, f"Saving {total_scored} banger flags...")

    saved = _save_banger_flags(results, force=force)

    # Log distribution summary
    high_conf = sum(1 for r in results if r["confidence"] >= 0.75)
    high_banger = sum(1 for r in results if r["banger_score"] >= 0.7)
    logger.info(
        f"Banger detection complete: {total_scored} scored, {saved} saved, "
        f"{high_banger} high-banger (≥0.7), {high_conf} high-confidence (≥0.75)"
    )

    if progress_callback:
        progress_callback(
            total_scored, total_scored,
            f"Banger detection complete: {saved} tracks flagged, "
            f"{high_banger} bangers, {high_conf} high-confidence"
        )

    return {
        "tracks_scored": total_scored,
        "tracks_saved": saved,
        "high_banger_count": high_banger,
        "high_confidence_count": high_conf,
    }
