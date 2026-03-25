"""Banger detection from existing Last.fm popularity data.

Computes per-track banger scores using two independent signals:
1. Within-artist rank — log(playcount) rank vs same artist's other tracks
2. Global listener percentile — log(listeners) percentile across library

No external API calls needed — works entirely from lastfm_stats table.
"""

import json
import logging
import math
from typing import Any

from app.database_pg import get_connection

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
            # Fetch all tracks with Last.fm stats and their primary artist
            cur.execute("""
                SELECT ls.track_id, ls.playcount, ls.listeners,
                       ta.artist_id, a.name as artist_name
                FROM lastfm_stats ls
                JOIN track_artists ta ON ls.track_id = ta.track_id AND ta.role = 'primary'
                JOIN artists a ON ta.artist_id = a.id
                WHERE ls.playcount > 0 OR ls.listeners > 0
            """)
            rows = cur.fetchall()

    if not rows:
        logger.warning("No Last.fm stats found — cannot compute banger scores")
        return []

    # Build data structures
    tracks = []
    artist_tracks: dict[str, list[dict]] = {}  # artist_id -> [track_data]
    all_listeners: list[float] = []

    for track_id, playcount, listeners, artist_id, artist_name in rows:
        td = {
            "track_id": str(track_id),
            "playcount": playcount or 0,
            "listeners": listeners or 0,
            "artist_id": str(artist_id),
            "artist_name": artist_name,
            "log_playcount": math.log1p(playcount or 0),
            "log_listeners": math.log1p(listeners or 0),
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

    # Compute within-artist rankings
    artist_rankings: dict[str, dict[str, float]] = {}  # artist_id -> {track_id -> rank_score}
    for artist_id, atracks in artist_tracks.items():
        if len(atracks) < _MIN_ARTIST_TRACKS:
            continue  # fallback to global only for small catalogs

        # Sort by log_playcount descending
        sorted_tracks = sorted(atracks, key=lambda t: t["log_playcount"], reverse=True)
        n = len(sorted_tracks)
        top_n = max(1, int(n * _WITHIN_ARTIST_TOP_FRACTION))

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

        # Composite banger score (independent signals)
        banger_score = (
            within_artist_score * 0.60 +
            global_listener_score * 0.40
        )
        banger_score = min(1.0, max(0.0, banger_score))

        # Confidence based on signal agreement
        if has_artist_signal and has_global_signal:
            confidence = 0.85 + min(0.15, banger_score * 0.15)
        elif has_artist_signal or has_global_signal:
            confidence = 0.55 + min(0.25, banger_score * 0.25)
        elif banger_score > 0.3:
            confidence = 0.25 + min(0.25, banger_score * 0.25)
        else:
            confidence = max(0.05, banger_score * 0.5)

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
