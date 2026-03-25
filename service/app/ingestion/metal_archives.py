"""Metal Archives (Encyclopaedia Metallum) scraper for album legitimacy data.

Uses direct HTTP requests to the Metal Archives JSON/HTML API to fetch album
ratings and review counts, then matches them against local database albums
via fuzzy title + year matching.
"""

import asyncio
import logging
import re
from difflib import SequenceMatcher
from typing import Any

import json as _json
import subprocess
from lxml import html as lxml_html

from app.database_pg import get_connection

logger = logging.getLogger(__name__)

_MA_BASE = "https://www.metal-archives.com"
_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def _ma_get(url: str, *, accept: str = "application/json", referer: str | None = None) -> str:
    """Fetch a URL from Metal Archives using curl (bypasses TLS fingerprinting blocks)."""
    cmd = [
        "curl", "-s", "-f", "--max-time", "20",
        "-H", f"User-Agent: {_UA}",
        "-H", f"Accept: {accept}",
        "-H", "Accept-Language: en-US,en;q=0.9",
    ]
    if referer:
        cmd += ["-H", f"Referer: {referer}"]
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed (rc={result.returncode}): {result.stderr[:200]}")
    return result.stdout

# Suffixes stripped before fuzzy comparison
_STRIP_SUFFIXES = re.compile(
    r"\s*[\(\[]?"
    r"(deluxe\s*edition|remastered|remaster|reissue|anniversary\s*edition|"
    r"expanded\s*edition|bonus\s*tracks?|special\s*edition|limited\s*edition|"
    r"digipak|vinyl|jewel\s*case)"
    r"[\)\]]?\s*$",
    re.IGNORECASE,
)


def _normalize_title(title: str) -> str:
    """Normalize album title for comparison."""
    title = _STRIP_SUFFIXES.sub("", title).strip()
    title = re.sub(r"\s+", " ", title).lower().strip()
    title = title.strip(".-–—")
    return title


def _match_confidence(local_title: str, local_year: int | None,
                      ma_title: str, ma_year: int | None) -> float:
    """Compute match confidence between a local album and an MA album.

    Returns 0.0–1.0.  Factors: title similarity (70%) + year proximity (30%).
    """
    norm_local = _normalize_title(local_title)
    norm_ma = _normalize_title(ma_title)

    title_sim = SequenceMatcher(None, norm_local, norm_ma).ratio()

    year_score = 0.5  # neutral when either year is missing
    if local_year and ma_year:
        diff = abs(local_year - ma_year)
        if diff == 0:
            year_score = 1.0
        elif diff == 1:
            year_score = 0.8
        elif diff <= 3:
            year_score = 0.4
        else:
            year_score = 0.0

    return title_sim * 0.70 + year_score * 0.30


# Subgenre keywords ranked by specificity (more specific = higher priority)
_SPECIFIC_GENRES = ("thrash", "death", "black", "doom", "grind", "sludge", "stoner",
                    "progressive", "power", "speed", "folk", "symphonic", "gothic",
                    "industrial", "metalcore", "deathcore", "post-metal", "djent")


def _genre_specificity(genre: str) -> int:
    """Score how specific a MA genre string is (higher = more specific)."""
    g = genre.lower()
    score = 0
    for kw in _SPECIFIC_GENRES:
        if kw in g:
            score += 2
    # Plain "Heavy Metal" is less specific than subgenres
    if "heavy metal" in g and score == 0:
        score = 1
    return score


def _search_band_candidates(artist_name: str) -> list[int]:
    """Search MA for a band by name. Returns ranked list of candidate band IDs."""
    url = f"{_MA_BASE}/search/ajax-band-search/"
    params = {
        "field": "name",
        "query": artist_name,
        "sEcho": 1,
        "iDisplayStart": 0,
        "iDisplayLength": 30,
    }
    try:
        from urllib.parse import urlencode
        full_url = f"{url}?{urlencode(params)}"
        raw = _ma_get(
            full_url,
            referer=f"{_MA_BASE}/search?searchString={artist_name}&type=band_name",
        )
        data = _json.loads(raw)
    except Exception as e:
        logger.warning(f"MA band search failed for '{artist_name}': {e}")
        return []

    rows = data.get("aaData", [])
    if not rows:
        return []

    band_id_re = re.compile(r"/bands/[^/]+/(\d+)")
    exact: list[tuple[int, str, int]] = []   # (id, genre, specificity)
    others: list[tuple[int, str, int]] = []

    for row in rows:
        cell = row[0] if isinstance(row, list) else str(row)
        genre = row[1] if isinstance(row, list) and len(row) > 1 else ""
        name_match = re.search(r">([^<]+)<", cell)
        name = name_match.group(1).strip() if name_match else ""
        id_match = band_id_re.search(cell)
        if not id_match:
            continue
        bid = int(id_match.group(1))
        spec = _genre_specificity(genre)
        if name.lower() == artist_name.lower():
            exact.append((bid, genre, spec))
        else:
            others.append((bid, genre, spec))

    # Sort by genre specificity descending (more specific subgenres first)
    exact.sort(key=lambda x: x[2], reverse=True)
    others.sort(key=lambda x: x[2], reverse=True)

    return [bid for bid, _, _ in exact] + [bid for bid, _, _ in others]


def _parse_discography(raw_html: str) -> list[dict[str, Any]]:
    """Parse MA discography HTML into album dicts."""
    try:
        tree = lxml_html.fromstring(raw_html)
    except Exception:
        return []

    albums = []
    for row in tree.xpath("//tr"):
        cells = row.xpath("td")
        if len(cells) < 4:
            continue

        link_el = cells[0].xpath(".//a")
        if not link_el:
            continue

        title = link_el[0].text_content().strip()
        album_url = link_el[0].get("href", "")
        album_type = cells[1].text_content().strip().lower()

        if album_type not in ("full-length", "ep", "compilation", "live album"):
            continue

        year_text = cells[2].text_content().strip()
        year = None
        year_match = re.search(r"\d{4}", year_text)
        if year_match:
            year = int(year_match.group())

        review_text = cells[3].text_content().strip()
        review_count = 0
        rating = None
        review_match = re.match(r"(\d+)\s*\((\d+)%\)", review_text)
        if review_match:
            review_count = int(review_match.group(1))
            rating = float(review_match.group(2))

        albums.append({
            "title": title,
            "year": year,
            "url": album_url,
            "rating": rating,
            "review_count": review_count,
        })

    return albums


def _fetch_band_albums(artist_name: str) -> list[dict[str, Any]]:
    """Search Metal Archives for a band and return album data.

    Tries multiple candidate bands (sorted by genre specificity) until one
    returns a non-empty discography.

    Returns list of dicts with keys: title, year, url, rating, review_count.
    """
    candidates = _search_band_candidates(artist_name)
    if not candidates:
        logger.debug(f"No MA band found for '{artist_name}'")
        return []

    # Try up to 3 candidates
    for band_id in candidates[:3]:
        disco_url = f"{_MA_BASE}/band/discography/id/{band_id}/tab/all"
        try:
            raw_html = _ma_get(disco_url, accept="text/html", referer=f"{_MA_BASE}/bands/{band_id}")
        except Exception as e:
            logger.debug(f"MA discography fetch failed for '{artist_name}' (id={band_id}): {e}")
            continue

        albums = _parse_discography(raw_html)
        if albums:
            logger.debug(f"MA: '{artist_name}' → band {band_id}, {len(albums)} albums")
            return albums

    logger.debug(f"No MA albums found for '{artist_name}' across {len(candidates[:3])} candidates")
    return albums if 'albums' in dir() else []


def _save_album_legitimacy(
    cur, album_id: str, ma_url: str | None, ma_rating: float | None,
    ma_review_count: int, match_confidence: float,
) -> None:
    """Upsert album legitimacy row."""
    cur.execute(
        """
        INSERT INTO album_legitimacy (album_id, ma_url, ma_rating, ma_review_count,
                                       match_confidence, scraped_at)
        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (album_id) DO UPDATE SET
            ma_url = COALESCE(excluded.ma_url, album_legitimacy.ma_url),
            ma_rating = excluded.ma_rating,
            ma_review_count = excluded.ma_review_count,
            match_confidence = excluded.match_confidence,
            scraped_at = excluded.scraped_at
        """,
        [album_id, ma_url, ma_rating, ma_review_count, match_confidence],
    )


async def enrich_albums_from_metal_archives(
    force: bool = False,
    delay_between_requests: float = 1.2,
    min_confidence: float = 0.7,
    progress_callback: Any = None,
) -> dict[str, int]:
    """Scrape Metal Archives for album ratings and match to local albums.

    Groups local albums by artist, searches MA per artist, then fuzzy-matches
    each local album against the MA discography.

    Args:
        force: Re-scrape albums that already have legitimacy data.
        delay_between_requests: Seconds between MA HTTP requests.
        min_confidence: Minimum match confidence to accept (0-1).
        progress_callback: Optional (current, total, message) callback.

    Returns:
        Stats dict with counts of processed/matched/skipped albums.
    """
    # Fetch local albums grouped by primary artist
    with get_connection() as conn:
        with conn.cursor() as cur:
            if force:
                cur.execute("""
                    SELECT DISTINCT a.name, a.id as artist_id
                    FROM artists a
                    JOIN album_artists aa ON a.id = aa.artist_id
                    ORDER BY a.name
                """)
            else:
                cur.execute("""
                    SELECT DISTINCT a.name, a.id as artist_id
                    FROM artists a
                    JOIN album_artists aa ON a.id = aa.artist_id
                    WHERE NOT EXISTS (
                        SELECT 1 FROM album_legitimacy al
                        JOIN track_albums ta2 ON ta2.album_id = al.album_id
                        JOIN track_artists ta3 ON ta3.track_id = ta2.track_id
                        WHERE ta3.artist_id = a.id
                    )
                    ORDER BY a.name
                """)
            artists = cur.fetchall()

    stats = {
        "artists_processed": 0,
        "albums_matched": 0,
        "albums_skipped_low_confidence": 0,
        "albums_no_ma_data": 0,
        "errors": 0,
    }
    total_artists = len(artists)
    logger.info(f"MA enrichment: {total_artists} artists to process (force={force})")

    for i, (artist_name, artist_id) in enumerate(artists):
        # Fetch local albums for this artist
        with get_connection() as conn:
            with conn.cursor() as cur:
                if force:
                    cur.execute("""
                        SELECT al.id, al.title, al.year
                        FROM albums al
                        JOIN album_artists aa ON al.id = aa.album_id
                        WHERE aa.artist_id = %s
                    """, [str(artist_id)])
                else:
                    cur.execute("""
                        SELECT al.id, al.title, al.year
                        FROM albums al
                        JOIN album_artists aa ON al.id = aa.album_id
                        LEFT JOIN album_legitimacy leg ON al.id = leg.album_id
                        WHERE aa.artist_id = %s AND leg.album_id IS NULL
                    """, [str(artist_id)])
                local_albums = cur.fetchall()

        if not local_albums:
            stats["artists_processed"] += 1
            continue

        # Search MA for this artist (blocking I/O in thread)
        try:
            ma_albums = await asyncio.to_thread(_fetch_band_albums, artist_name)
        except Exception as e:
            logger.warning(f"MA fetch failed for '{artist_name}': {e}")
            stats["errors"] += 1
            await asyncio.sleep(delay_between_requests)
            continue

        # Match local albums to MA albums
        with get_connection() as conn:
            with conn.cursor() as cur:
                for album_id, album_title, album_year in local_albums:
                    if not ma_albums:
                        stats["albums_no_ma_data"] += 1
                        continue

                    # Find best MA match
                    best_match = None
                    best_conf = 0.0
                    for ma_album in ma_albums:
                        conf = _match_confidence(
                            album_title, album_year,
                            ma_album["title"], ma_album["year"],
                        )
                        if conf > best_conf:
                            best_conf = conf
                            best_match = ma_album

                    if best_conf >= min_confidence and best_match:
                        _save_album_legitimacy(
                            cur,
                            str(album_id),
                            best_match.get("url"),
                            best_match.get("rating"),
                            best_match.get("review_count", 0),
                            best_conf,
                        )
                        stats["albums_matched"] += 1
                        logger.debug(
                            f"Matched '{album_title}' → MA '{best_match['title']}' "
                            f"(conf={best_conf:.2f}, rating={best_match.get('rating')})"
                        )
                    else:
                        stats["albums_skipped_low_confidence"] += 1
                        if best_match:
                            logger.debug(
                                f"Low confidence for '{album_title}' → "
                                f"MA '{best_match['title']}' (conf={best_conf:.2f})"
                            )

        stats["artists_processed"] += 1

        if progress_callback and (i + 1) % 5 == 0:
            progress_callback(
                i + 1, total_artists,
                f"MA: {i + 1}/{total_artists} artists, "
                f"{stats['albums_matched']} matched"
            )

        if (i + 1) % 20 == 0:
            logger.info(
                f"MA enrichment: {i + 1}/{total_artists} artists, "
                f"{stats['albums_matched']} matched, "
                f"{stats['albums_skipped_low_confidence']} low confidence"
            )

        await asyncio.sleep(delay_between_requests)

    if progress_callback:
        progress_callback(
            total_artists, total_artists,
            f"MA enrichment complete: {stats['albums_matched']} albums matched"
        )

    logger.info(f"MA enrichment complete: {stats}")
    return stats
