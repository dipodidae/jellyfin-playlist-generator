"""
Track transition memory.

Records consecutive track pairs from generated playlists and provides
historical transition bonuses for beam search scoring.
"""

import logging

from app.database_pg import get_connection

logger = logging.getLogger(__name__)

_MAX_BONUS = 0.05


def record_transitions(playlist_track_ids: list[str]) -> None:
    """
    Upsert consecutive track pairs from a generated playlist.

    Increments play_count for each (track_a, track_b) pair and updates
    last_used to now.
    """
    if len(playlist_track_ids) < 2:
        return

    pairs = [
        (playlist_track_ids[i], playlist_track_ids[i + 1])
        for i in range(len(playlist_track_ids) - 1)
    ]

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO track_transitions (track_a_id, track_b_id, play_count, last_used)
                    VALUES (%s::uuid, %s::uuid, 1, now())
                    ON CONFLICT (track_a_id, track_b_id) DO UPDATE SET
                        play_count = track_transitions.play_count + 1,
                        last_used  = now()
                """, pairs)
            conn.commit()
        logger.debug(f"Recorded {len(pairs)} transition pairs")
    except Exception as e:
        logger.warning(f"Failed to record transitions: {e}")


def record_skip(track_a_id: str, track_b_id: str) -> None:
    """
    Increment skip_count for a specific transition pair.

    Called when the user signals a bad transition (future frontend integration).
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO track_transitions (track_a_id, track_b_id, play_count, skip_count, last_used)
                    VALUES (%s::uuid, %s::uuid, 0, 1, now())
                    ON CONFLICT (track_a_id, track_b_id) DO UPDATE SET
                        skip_count = track_transitions.skip_count + 1,
                        last_used  = now()
                """, (track_a_id, track_b_id))
            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to record skip: {e}")


def load_transition_bonuses(track_ids: list[str]) -> dict[tuple[str, str], float]:
    """
    Batch-load historical transition bonuses for a set of track IDs.

    Returns a dict keyed by (track_a_id, track_b_id) with bonus values in [0, _MAX_BONUS].

    Formula: bonus = (play_count / (play_count + skip_count + 1)) * _MAX_BONUS

    A single DB query is used — no N+1 penalty during beam search.
    """
    if not track_ids:
        return {}

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT track_a_id::text, track_b_id::text, play_count, skip_count
                    FROM track_transitions
                    WHERE track_a_id = ANY(%s::uuid[])
                      AND track_b_id = ANY(%s::uuid[])
                """, (track_ids, track_ids))
                rows = cur.fetchall()

        bonuses: dict[tuple[str, str], float] = {}
        for a_id, b_id, play_count, skip_count in rows:
            raw = play_count / (play_count + skip_count + 1)
            bonuses[(a_id, b_id)] = raw * _MAX_BONUS

        logger.debug(f"Loaded {len(bonuses)} transition bonuses for {len(track_ids)} tracks")
        return bonuses

    except Exception as e:
        logger.warning(f"Failed to load transition bonuses: {e}")
        return {}
