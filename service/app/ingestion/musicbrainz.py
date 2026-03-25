"""MusicBrainz identity resolution for artists and albums.

Uses musicbrainzngs to resolve local artists/albums to canonical MusicBrainz IDs
(MBIDs). These serve as universal join keys for all external enrichment sources
(Last.fm, RYM, Metal Archives, etc.).

Rate-limited to 1 request/second per MB API terms of service.
"""

import asyncio
import logging
import re
from difflib import SequenceMatcher
from typing import Any

import musicbrainzngs

from app.config import settings
from app.database_pg import get_connection

logger = logging.getLogger(__name__)

_MB_INITIALIZED = False


def _ensure_init() -> None:
    """Initialize musicbrainzngs with app credentials (once)."""
    global _MB_INITIALIZED
    if _MB_INITIALIZED:
        return
    musicbrainzngs.set_useragent(
        settings.musicbrainz_app_name,
        settings.musicbrainz_app_version,
        settings.musicbrainz_contact or None,
    )
    musicbrainzngs.set_rate_limit(limit_or_interval=1.0)
    _MB_INITIALIZED = True


def _normalize(text: str) -> str:
    """Normalize text for fuzzy comparison."""
    text = re.sub(r"\s+", " ", text).lower().strip()
    text = re.sub(
        r"\s*[\(\[]?"
        r"(deluxe\s*edition|remastered|remaster|reissue|anniversary\s*edition|"
        r"expanded\s*edition|bonus\s*tracks?|special\s*edition|limited\s*edition|"
        r"digipak|vinyl|jewel\s*case)"
        r"[\)\]]?\s*$",
        "", text, flags=re.IGNORECASE,
    ).strip()
    return text


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


# ---------------------------------------------------------------------------
# Artist resolution
# ---------------------------------------------------------------------------

def _search_artist(name: str) -> dict[str, Any] | None:
    """Search MusicBrainz for an artist by name. Returns best match or None."""
    _ensure_init()
    try:
        result = musicbrainzngs.search_artists(artist=name, limit=5)
    except Exception as e:
        logger.debug(f"MB artist search failed for '{name}': {e}")
        return None

    artists = result.get("artist-list", [])
    if not artists:
        return None

    best = None
    best_score = 0.0
    for a in artists:
        mb_name = a.get("name", "")
        sim = _title_similarity(name, mb_name)
        # MB returns a score 0-100 as string
        mb_score = int(a.get("ext:score", "0")) / 100.0
        combined = sim * 0.6 + mb_score * 0.4
        if combined > best_score:
            best_score = combined
            best = {
                "mbid": a["id"],
                "name": mb_name,
                "score": best_score,
                "type": a.get("type", ""),
                "disambiguation": a.get("disambiguation", ""),
            }

    if best and best["score"] >= 0.70:
        return best
    return None


def _save_artist_mbid(cur, artist_id: str, mbid: str, score: float) -> None:
    """Store MBID on artist row and cache the lookup."""
    cur.execute(
        "UPDATE artists SET musicbrainz_id = %s WHERE id = %s AND musicbrainz_id IS NULL",
        [mbid, artist_id],
    )
    cur.execute(
        """
        INSERT INTO mb_lookup_cache (entity_type, local_id, mbid, match_score)
        VALUES ('artist', %s, %s, %s)
        ON CONFLICT (entity_type, local_id) DO UPDATE SET
            mbid = EXCLUDED.mbid,
            match_score = EXCLUDED.match_score,
            lookup_at = now()
        """,
        [artist_id, mbid, score],
    )


# ---------------------------------------------------------------------------
# Album / release-group resolution
# ---------------------------------------------------------------------------

def _search_release_group(
    title: str, artist_name: str, artist_mbid: str | None, year: int | None,
) -> dict[str, Any] | None:
    """Search MB for a release group matching a local album."""
    _ensure_init()
    try:
        kwargs: dict[str, Any] = {"releasegroup": title, "limit": 10}
        if artist_mbid:
            kwargs["arid"] = artist_mbid
        else:
            kwargs["artist"] = artist_name
        result = musicbrainzngs.search_release_groups(**kwargs)
    except Exception as e:
        logger.debug(f"MB release-group search failed for '{title}': {e}")
        return None

    rgs = result.get("release-group-list", [])
    if not rgs:
        return None

    best = None
    best_score = 0.0
    for rg in rgs:
        rg_title = rg.get("title", "")
        title_sim = _title_similarity(title, rg_title)

        # Year proximity bonus
        year_score = 0.5
        rg_year = None
        first_release = rg.get("first-release-date", "")
        if first_release and len(first_release) >= 4:
            try:
                rg_year = int(first_release[:4])
            except ValueError:
                pass
        if year and rg_year:
            diff = abs(year - rg_year)
            if diff == 0:
                year_score = 1.0
            elif diff == 1:
                year_score = 0.8
            elif diff <= 3:
                year_score = 0.4
            else:
                year_score = 0.0

        mb_score = int(rg.get("ext:score", "0")) / 100.0
        combined = title_sim * 0.45 + year_score * 0.20 + mb_score * 0.35

        if combined > best_score:
            best_score = combined
            artist_credit = ""
            ac = rg.get("artist-credit", [])
            if ac and isinstance(ac, list):
                parts = []
                for item in ac:
                    if isinstance(item, dict) and "artist" in item:
                        parts.append(item["artist"].get("name", ""))
                    elif isinstance(item, str):
                        parts.append(item)
                artist_credit = "".join(parts)

            best = {
                "mbid": rg["id"],
                "title": rg_title,
                "artist_credit": artist_credit,
                "primary_type": rg.get("primary-type", ""),
                "year": rg_year,
                "score": best_score,
            }

    if best and best["score"] >= 0.65:
        return best
    return None


def _save_album_mbid(cur, album_id: str, rg: dict[str, Any]) -> None:
    """Store MBID on album row, cache release group, and cache lookup."""
    cur.execute(
        "UPDATE albums SET musicbrainz_id = %s WHERE id = %s AND musicbrainz_id IS NULL",
        [rg["mbid"], album_id],
    )
    cur.execute(
        """
        INSERT INTO mb_release_groups (mbid, title, artist_credit, primary_type, first_release_year)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (mbid) DO NOTHING
        """,
        [rg["mbid"], rg["title"], rg.get("artist_credit", ""),
         rg.get("primary_type", ""), rg.get("year")],
    )
    cur.execute(
        """
        INSERT INTO mb_lookup_cache (entity_type, local_id, mbid, match_score)
        VALUES ('release_group', %s, %s, %s)
        ON CONFLICT (entity_type, local_id) DO UPDATE SET
            mbid = EXCLUDED.mbid,
            match_score = EXCLUDED.match_score,
            lookup_at = now()
        """,
        [album_id, rg["mbid"], rg["score"]],
    )


# ---------------------------------------------------------------------------
# Batch pipeline
# ---------------------------------------------------------------------------

async def resolve_musicbrainz_ids(
    force: bool = False,
    progress_callback: Any = None,
) -> dict[str, int]:
    """Resolve MusicBrainz IDs for all artists and albums.

    Phase 1: Resolve artists (name → MBID).
    Phase 2: Resolve albums (title + artist MBID → release group MBID).

    Args:
        force: Re-resolve entities that already have MBIDs.
        progress_callback: Optional (current, total, message) callback.

    Returns:
        Stats dict with counts.
    """
    stats = {
        "artists_processed": 0,
        "artists_resolved": 0,
        "artists_skipped": 0,
        "albums_processed": 0,
        "albums_resolved": 0,
        "albums_skipped": 0,
        "errors": 0,
    }

    # --- Phase 1: Artists ---
    with get_connection() as conn:
        with conn.cursor() as cur:
            if force:
                cur.execute("""
                    SELECT a.id, a.name FROM artists a
                    ORDER BY (SELECT COUNT(*) FROM track_artists ta WHERE ta.artist_id = a.id) DESC
                """)
            else:
                cur.execute("""
                    SELECT a.id, a.name FROM artists a
                    LEFT JOIN mb_lookup_cache mc
                        ON mc.entity_type = 'artist' AND mc.local_id = a.id
                    WHERE a.musicbrainz_id IS NULL AND mc.local_id IS NULL
                    ORDER BY (SELECT COUNT(*) FROM track_artists ta WHERE ta.artist_id = a.id) DESC
                """)
            artists = cur.fetchall()

    total_artists = len(artists)
    logger.info(f"MB resolution: {total_artists} artists to process (force={force})")

    if progress_callback:
        progress_callback(0, total_artists + 1, f"Resolving {total_artists} artists...")

    for i, (artist_id, artist_name) in enumerate(artists):
        try:
            match = await asyncio.to_thread(_search_artist, artist_name)
            if match:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        _save_artist_mbid(cur, str(artist_id), match["mbid"], match["score"])
                stats["artists_resolved"] += 1
                logger.debug(f"MB: '{artist_name}' → {match['mbid']} (score={match['score']:.2f})")
            else:
                # Cache the miss so we don't retry
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO mb_lookup_cache (entity_type, local_id, mbid, match_score)
                            VALUES ('artist', %s, NULL, 0.0)
                            ON CONFLICT (entity_type, local_id) DO NOTHING
                            """,
                            [str(artist_id)],
                        )
                stats["artists_skipped"] += 1
        except Exception as e:
            logger.warning(f"MB artist resolution error for '{artist_name}': {e}")
            stats["errors"] += 1

        stats["artists_processed"] += 1

        if progress_callback and (i + 1) % 10 == 0:
            progress_callback(
                i + 1, total_artists + 1,
                f"Artists: {i + 1}/{total_artists} ({stats['artists_resolved']} resolved)",
            )

        if (i + 1) % 50 == 0:
            logger.info(
                f"MB artists: {i + 1}/{total_artists}, "
                f"{stats['artists_resolved']} resolved, {stats['artists_skipped']} skipped"
            )

    # --- Phase 2: Albums ---
    with get_connection() as conn:
        with conn.cursor() as cur:
            if force:
                cur.execute("""
                    SELECT al.id, al.title, al.year, a.name as artist_name, a.musicbrainz_id as artist_mbid
                    FROM albums al
                    JOIN album_artists aa ON al.id = aa.album_id
                    JOIN artists a ON aa.artist_id = a.id
                    ORDER BY al.title
                """)
            else:
                cur.execute("""
                    SELECT al.id, al.title, al.year, a.name as artist_name, a.musicbrainz_id as artist_mbid
                    FROM albums al
                    JOIN album_artists aa ON al.id = aa.album_id
                    JOIN artists a ON aa.artist_id = a.id
                    LEFT JOIN mb_lookup_cache mc
                        ON mc.entity_type = 'release_group' AND mc.local_id = al.id
                    WHERE al.musicbrainz_id IS NULL AND mc.local_id IS NULL
                    ORDER BY al.title
                """)
            albums = cur.fetchall()

    total_albums = len(albums)
    total_work = total_artists + total_albums
    logger.info(f"MB resolution: {total_albums} albums to process")

    if progress_callback:
        progress_callback(
            total_artists, total_work,
            f"Resolving {total_albums} albums...",
        )

    for i, (album_id, title, year, artist_name, artist_mbid) in enumerate(albums):
        try:
            match = await asyncio.to_thread(
                _search_release_group, title, artist_name, artist_mbid, year,
            )
            if match:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        _save_album_mbid(cur, str(album_id), match)
                stats["albums_resolved"] += 1
                logger.debug(f"MB: '{title}' → {match['mbid']} (score={match['score']:.2f})")
            else:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO mb_lookup_cache (entity_type, local_id, mbid, match_score)
                            VALUES ('release_group', %s, NULL, 0.0)
                            ON CONFLICT (entity_type, local_id) DO NOTHING
                            """,
                            [str(album_id)],
                        )
                stats["albums_skipped"] += 1
        except Exception as e:
            logger.warning(f"MB album resolution error for '{title}': {e}")
            stats["errors"] += 1

        stats["albums_processed"] += 1

        if progress_callback and (i + 1) % 10 == 0:
            progress_callback(
                total_artists + i + 1, total_work,
                f"Albums: {i + 1}/{total_albums} ({stats['albums_resolved']} resolved)",
            )

        if (i + 1) % 50 == 0:
            logger.info(
                f"MB albums: {i + 1}/{total_albums}, "
                f"{stats['albums_resolved']} resolved, {stats['albums_skipped']} skipped"
            )

    logger.info(f"MB resolution complete: {stats}")
    if progress_callback:
        progress_callback(
            total_work, total_work,
            f"MusicBrainz complete: {stats['artists_resolved']} artists, "
            f"{stats['albums_resolved']} albums resolved",
        )

    return stats
