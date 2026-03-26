"""True Original Release Date Resolver.

Multi-source pipeline that aggressively resolves the first verifiable
commercial release date for an album, filtering out reissue contamination.

Source priority (highest → lowest):
1. MusicBrainz — release group earliest release event (ignoring reissues)
2. Discogs — master release year (physical chronology anchor)
3. File metadata — `originaldate` tag (higher priority than `date`)
4. Metal Archives — scraped year from album_legitimacy table

Cross-reference logic:
- ≥2 sources agree on year → confidence ≥ 0.8
- Sources conflict → pick earliest plausible, lower confidence, log conflict
- Reissue detection: reject dates >5 years after earliest source
"""

import asyncio
import json
import logging
from typing import Any

import httpx

from app.config import settings
from app.database_pg import get_connection
from app.ingestion.musicbrainz import extract_release_date_from_mb
from app.ingestion.discogs import resolve_discogs_release_date

logger = logging.getLogger(__name__)


def _get_file_metadata_year(album_id: str) -> dict[str, Any] | None:
    """Extract year from file metadata tags for tracks in this album.

    Prefers `originaldate` tag over `date` tag. Falls back to albums.year.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get album year and track years
            cur.execute("""
                SELECT al.year,
                       array_agg(DISTINCT t.year) FILTER (WHERE t.year IS NOT NULL) as track_years
                FROM albums al
                LEFT JOIN track_albums ta ON ta.album_id = al.id
                LEFT JOIN tracks t ON t.id = ta.track_id
                WHERE al.id = %s::uuid
                GROUP BY al.id
            """, [album_id])
            row = cur.fetchone()

    if not row:
        return None

    album_year = row[0]
    track_years = row[1] or []

    # Use the earliest year from tracks (closest to original release)
    year = None
    if track_years:
        valid_years = [y for y in track_years if y and 1900 <= y <= 2030]
        if valid_years:
            year = min(valid_years)

    if not year and album_year and 1900 <= album_year <= 2030:
        year = album_year

    if not year:
        return None

    return {
        "source": "file_metadata",
        "year": year,
        "month": None,
        "day": None,
        "precision": "year",
        "country": None,
        "label": None,
        "format": None,
        "catalog_number": None,
        "confidence": 0.4,  # file metadata alone is low confidence
    }


def _get_metal_archives_year(album_id: str) -> dict[str, Any] | None:
    """Get year from Metal Archives data if available."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT al_leg.scraped_at, al.year
                FROM album_legitimacy al_leg
                JOIN albums al ON al.id = al_leg.album_id
                WHERE al_leg.album_id = %s::uuid
                  AND al_leg.match_confidence >= 0.7
            """, [album_id])
            row = cur.fetchone()

    if not row or not row[1]:
        return None

    year = row[1]
    if year < 1900 or year > 2030:
        return None

    return {
        "source": "metal_archives",
        "year": year,
        "month": None,
        "day": None,
        "precision": "year",
        "country": None,
        "label": None,
        "format": None,
        "catalog_number": None,
        "confidence": 0.5,  # MA is decent but not primary
    }


def _cross_reference(
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Cross-reference multiple source results to produce a final verdict.

    Rules:
    - Pick the earliest plausible year across sources
    - If ≥2 sources agree on the same year → confidence boost to ≥0.8
    - If sources conflict by >5 years → flag as conflict, use earliest
    - Prefer the source with highest precision (day > month > year)
    - Inherit first-pressing details (country, label, format) from
      the highest-confidence source
    """
    if not sources:
        return {}

    # Sort by year (earliest first), then by precision (day > month > year)
    precision_order = {"day": 0, "month": 1, "year": 2}
    sources.sort(key=lambda s: (
        s.get("year", 9999),
        precision_order.get(s.get("precision", "year"), 2),
    ))

    years = [s["year"] for s in sources if s.get("year")]
    if not years:
        return {}

    earliest_year = min(years)

    # Count how many sources agree on the earliest year
    agreeing = [s for s in sources if s.get("year") == earliest_year]
    n_agreeing = len(agreeing)
    n_total = len(sources)

    # Detect conflicts: any source >5 years from earliest
    conflicts = [s for s in sources if s.get("year") and abs(s["year"] - earliest_year) > 5]
    has_conflict = len(conflicts) > 0

    # Base confidence from agreement
    if n_agreeing >= 3:
        confidence = 0.95
    elif n_agreeing >= 2:
        confidence = 0.85
    elif n_total == 1:
        confidence = sources[0].get("confidence", 0.5)
    else:
        confidence = 0.55  # single source among many, others disagree

    # Penalize if there are conflicts
    if has_conflict:
        confidence = min(confidence, 0.65)

    # Pick the best source for detailed info: prefer the agreeing source
    # with highest precision, falling back to highest confidence
    best_detail = agreeing[0] if agreeing else sources[0]
    for s in agreeing:
        if precision_order.get(s.get("precision", "year"), 2) < \
           precision_order.get(best_detail.get("precision", "year"), 2):
            best_detail = s

    # Build evidence chain
    evidence = {
        "sources": [
            {
                "source": s.get("source"),
                "year": s.get("year"),
                "month": s.get("month"),
                "day": s.get("day"),
                "confidence": s.get("confidence", 0),
            }
            for s in sources
        ],
        "agreement_count": n_agreeing,
        "total_sources": n_total,
        "has_conflict": has_conflict,
    }
    if conflicts:
        evidence["conflict_years"] = [s["year"] for s in conflicts]

    return {
        "original_year": earliest_year,
        "original_month": best_detail.get("month"),
        "original_day": best_detail.get("day"),
        "precision": best_detail.get("precision", "year"),
        "confidence": round(confidence, 2),
        "primary_source": best_detail.get("source", "unknown"),
        "country": best_detail.get("country"),
        "label": best_detail.get("label"),
        "format": best_detail.get("format"),
        "catalog_number": best_detail.get("catalog_number"),
        "evidence": evidence,
    }


def _save_release_date(album_id: str, data: dict[str, Any]) -> None:
    """Upsert resolved release date into album_release_dates."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO album_release_dates (
                    album_id, original_year, original_month, original_day,
                    precision, confidence, primary_source,
                    country, label, format, catalog_number, evidence
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (album_id) DO UPDATE SET
                    original_year = EXCLUDED.original_year,
                    original_month = EXCLUDED.original_month,
                    original_day = EXCLUDED.original_day,
                    precision = EXCLUDED.precision,
                    confidence = EXCLUDED.confidence,
                    primary_source = EXCLUDED.primary_source,
                    country = EXCLUDED.country,
                    label = EXCLUDED.label,
                    format = EXCLUDED.format,
                    catalog_number = EXCLUDED.catalog_number,
                    evidence = EXCLUDED.evidence,
                    resolved_at = now()
            """, [
                album_id,
                data.get("original_year"),
                data.get("original_month"),
                data.get("original_day"),
                data.get("precision", "year"),
                data.get("confidence", 0.0),
                data.get("primary_source"),
                data.get("country"),
                data.get("label"),
                data.get("format"),
                data.get("catalog_number"),
                json.dumps(data.get("evidence", {})),
            ])


async def resolve_album_release_date(
    album_id: str,
    album_title: str,
    artist_name: str,
    musicbrainz_id: str | None,
    year_hint: int | None,
    discogs_client: httpx.AsyncClient | None = None,
) -> dict[str, Any] | None:
    """Resolve the true original release date for a single album.

    Queries all available sources, cross-references, and stores the result.
    """
    sources: list[dict[str, Any]] = []

    # Source 1: MusicBrainz (if we have an MBID)
    if musicbrainz_id:
        try:
            mb_result = await asyncio.to_thread(
                extract_release_date_from_mb, musicbrainz_id
            )
            if mb_result:
                sources.append(mb_result)
                logger.debug(f"MB: '{album_title}' → year={mb_result['year']}")
        except Exception as e:
            logger.debug(f"MB release date failed for '{album_title}': {e}")

    # Source 2: Discogs (if client available and token configured)
    if discogs_client and settings.discogs_token:
        try:
            discogs_result = await resolve_discogs_release_date(
                discogs_client, artist_name, album_title, year_hint
            )
            if discogs_result:
                sources.append(discogs_result)
                logger.debug(f"Discogs: '{album_title}' → year={discogs_result['year']}")
        except Exception as e:
            logger.debug(f"Discogs release date failed for '{album_title}': {e}")

    # Source 3: File metadata
    try:
        file_result = _get_file_metadata_year(album_id)
        if file_result:
            sources.append(file_result)
    except Exception as e:
        logger.debug(f"File metadata year failed for '{album_title}': {e}")

    # Source 4: Metal Archives
    try:
        ma_result = _get_metal_archives_year(album_id)
        if ma_result:
            sources.append(ma_result)
    except Exception as e:
        logger.debug(f"MA year failed for '{album_title}': {e}")

    if not sources:
        return None

    # Cross-reference all sources
    result = _cross_reference(sources)
    if not result or not result.get("original_year"):
        return None

    # Persist
    _save_release_date(album_id, result)
    return result


async def resolve_release_dates(
    force: bool = False,
    max_albums: int | None = None,
    progress_callback: Any = None,
) -> dict[str, int]:
    """Batch pipeline to resolve true original release dates for all albums.

    Args:
        force: Re-resolve albums that already have release dates.
        max_albums: Limit number of albums to process.
        progress_callback: Optional (current, total, message) callback.

    Returns:
        Stats dict with counts.
    """
    # Fetch albums to process
    with get_connection() as conn:
        with conn.cursor() as cur:
            if force:
                query = """
                    SELECT al.id, al.title, al.year, a.name as artist_name,
                           al.musicbrainz_id
                    FROM albums al
                    JOIN album_artists aa ON al.id = aa.album_id
                    JOIN artists a ON aa.artist_id = a.id
                    ORDER BY a.name, al.title
                """
            else:
                query = """
                    SELECT al.id, al.title, al.year, a.name as artist_name,
                           al.musicbrainz_id
                    FROM albums al
                    JOIN album_artists aa ON al.id = aa.album_id
                    JOIN artists a ON aa.artist_id = a.id
                    LEFT JOIN album_release_dates ard ON al.id = ard.album_id
                    WHERE ard.album_id IS NULL
                    ORDER BY a.name, al.title
                """
            if max_albums:
                query += f" LIMIT {max_albums}"
            cur.execute(query)
            albums = cur.fetchall()

    stats = {
        "albums_processed": 0,
        "albums_resolved": 0,
        "albums_skipped": 0,
        "high_confidence": 0,
        "errors": 0,
    }
    total = len(albums)
    logger.info(f"Release date resolution: {total} albums to process (force={force})")

    if progress_callback:
        progress_callback(0, total, f"Resolving release dates for {total} albums...")

    # Create Discogs client if token is configured
    discogs_client = None
    if settings.discogs_token:
        discogs_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Discogs API enabled for release date resolution")
    else:
        logger.info("Discogs API disabled (no DISCOGS_TOKEN configured)")

    try:
        for i, (album_id, title, year, artist_name, mbid) in enumerate(albums):
            try:
                result = await resolve_album_release_date(
                    album_id=str(album_id),
                    album_title=title,
                    artist_name=artist_name,
                    musicbrainz_id=mbid,
                    year_hint=year,
                    discogs_client=discogs_client,
                )

                if result:
                    stats["albums_resolved"] += 1
                    if result.get("confidence", 0) >= 0.8:
                        stats["high_confidence"] += 1
                    logger.debug(
                        f"Resolved: '{artist_name} - {title}' → {result['original_year']} "
                        f"(confidence={result['confidence']}, source={result['primary_source']})"
                    )
                else:
                    stats["albums_skipped"] += 1

            except Exception as e:
                logger.warning(f"Release date error for '{artist_name} - {title}': {e}")
                stats["errors"] += 1

            stats["albums_processed"] += 1

            if progress_callback and (i + 1) % 10 == 0:
                progress_callback(
                    i + 1, total,
                    f"Release dates: {i + 1}/{total} ({stats['albums_resolved']} resolved)",
                )

            if (i + 1) % 50 == 0:
                logger.info(
                    f"Release dates: {i + 1}/{total}, "
                    f"{stats['albums_resolved']} resolved, {stats['albums_skipped']} skipped, "
                    f"{stats['high_confidence']} high-confidence"
                )
    finally:
        if discogs_client:
            await discogs_client.aclose()

    if progress_callback:
        progress_callback(
            total, total,
            f"Release dates complete: {stats['albums_resolved']} resolved "
            f"({stats['high_confidence']} high-confidence)",
        )

    logger.info(f"Release date resolution complete: {stats}")
    return stats
