"""Populate track_studio_scores from track + album titles using the pure classifier."""

import logging

from app.database_pg import get_connection
from app.ingestion.version_classifier import classify_version

logger = logging.getLogger(__name__)


def backfill_studio_scores() -> dict[str, int]:
    """Classify every track's version and upsert into track_studio_scores."""
    stats = {"processed": 0}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT t.id, t.title, COALESCE(al.title, '')
                FROM tracks t
                LEFT JOIN track_albums ta ON ta.track_id = t.id
                LEFT JOIN albums al ON al.id = ta.album_id
            """)
            rows = cur.fetchall()
            for track_id, title, album_title in rows:
                vtype, score = classify_version(title or "", album_title or "", [])
                cur.execute("""
                    INSERT INTO track_studio_scores
                        (track_id, version_type, studio_score, computed_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (track_id) DO UPDATE
                        SET version_type = EXCLUDED.version_type,
                            studio_score = EXCLUDED.studio_score,
                            computed_at = now()
                """, (track_id, vtype, score))
                stats["processed"] += 1
        conn.commit()
    logger.info("Studio-score backfill complete: %s", stats)
    return stats
