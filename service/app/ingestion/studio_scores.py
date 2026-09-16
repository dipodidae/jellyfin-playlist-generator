"""Populate track_studio_scores from track + album titles using the pure classifier."""

import logging

from app.database_pg import get_connection
from app.ingestion.version_classifier import classify_version

logger = logging.getLogger(__name__)


def backfill_studio_scores(
    progress_callback=None,
    only_missing: bool = True,
    max_tracks: int | None = None,
) -> dict[str, int]:
    """Classify every track's version and upsert into track_studio_scores.

    Pure metadata (title + album title), no I/O beyond the DB, so this is
    cheap -- but it was only ever reachable through /sync/full-pipeline, the
    monolithic endpoint retired on 2026-09-03. Decomposing that pipeline into
    per-stage endpoints missed this one, so nothing has computed a studio score
    since: 9,149 of 162,775 tracks had none on 2026-09-16.

    only_missing defaults True because a re-run over the whole library is only
    needed after classify_version itself changes; pass False for that.
    """
    stats = {"processed": 0}
    with get_connection() as conn:
        with conn.cursor() as cur:
            where_sql = (
                " WHERE NOT EXISTS (SELECT 1 FROM track_studio_scores tss "
                "WHERE tss.track_id = t.id)"
                if only_missing else ""
            )
            limit_sql = f" LIMIT {int(max_tracks)}" if max_tracks else ""
            cur.execute("""
                SELECT t.id, t.title, COALESCE(al.title, '')
                FROM tracks t
                LEFT JOIN track_albums ta ON ta.track_id = t.id
                LEFT JOIN albums al ON al.id = ta.album_id
            """ + where_sql + limit_sql)
            rows = cur.fetchall()
            total = len(rows)
            if progress_callback:
                progress_callback(0, total, f"Classifying {total} tracks...")
            for i, (track_id, title, album_title) in enumerate(rows):
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
                if progress_callback and (i + 1) % 2000 == 0:
                    progress_callback(i + 1, total, f"Classified {i + 1}/{total}")
        conn.commit()
    if progress_callback:
        progress_callback(
            stats["processed"], stats["processed"],
            f"Studio scoring complete: {stats['processed']} classified",
        )
    logger.info("Studio-score backfill complete: %s", stats)
    return stats
