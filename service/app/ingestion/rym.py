"""RateYourMusic scraper for album-level cultural data.

Batch-ingested, cached, slowly updated dataset — NOT a live API dependency.
Scraping is disabled by default (rym_scrape_enabled=False in config).

Extracts: ratings, vote counts, genres, descriptors, list counts.
Stores raw HTML in rym_scrape_cache to avoid re-scraping on parser updates.
"""

import asyncio
import json
import logging
import math
import random
import re
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.database_pg import get_connection

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
_RYM_BASE = "https://rateyourmusic.com"


# ---------------------------------------------------------------------------
# HTTP layer (throttled, cached)
# ---------------------------------------------------------------------------

async def _rym_get(url: str, client: httpx.AsyncClient) -> str:
    """Fetch a RYM page with throttling and caching."""
    # Check cache first
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT html FROM rym_scrape_cache WHERE url = %s", [url]
            )
            row = cur.fetchone()
            if row:
                return row[0]

    delay = random.uniform(settings.rym_scrape_delay_min, settings.rym_scrape_delay_max)
    await asyncio.sleep(delay)

    resp = await client.get(url, headers={"User-Agent": _UA}, follow_redirects=True)
    resp.raise_for_status()
    html = resp.text

    # Cache raw HTML
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rym_scrape_cache (url, html, fetched_at)
                VALUES (%s, %s, now())
                ON CONFLICT (url) DO UPDATE SET html = EXCLUDED.html, fetched_at = now()
                """,
                [url, html],
            )

    return html


# ---------------------------------------------------------------------------
# Search + parsing
# ---------------------------------------------------------------------------

def _parse_album_page(html: str) -> dict[str, Any] | None:
    """Parse a RYM album page into structured data."""
    soup = BeautifulSoup(html, "html.parser")

    data: dict[str, Any] = {}

    # Rating
    rating_el = soup.select_one(".avg_rating")
    if rating_el:
        try:
            data["rym_rating"] = float(rating_el.get_text(strip=True))
        except (ValueError, TypeError):
            data["rym_rating"] = None
    else:
        data["rym_rating"] = None

    # Vote count
    num_ratings_el = soup.select_one(".num_ratings span.num_ratings b") or soup.select_one(".num_ratings b")
    if num_ratings_el:
        text = num_ratings_el.get_text(strip=True).replace(",", "")
        try:
            data["rym_votes"] = int(text)
        except (ValueError, TypeError):
            data["rym_votes"] = 0
    else:
        data["rym_votes"] = 0

    # Genres (primary + secondary)
    genres = []
    for genre_el in soup.select(".release_pri_genres .genre, .release_sec_genres .genre"):
        genre_name = genre_el.get_text(strip=True)
        if genre_name:
            genres.append(genre_name)
    data["genres"] = genres

    # Descriptors
    descriptors = []
    desc_el = soup.select_one(".release_descriptors")
    if desc_el:
        for link in desc_el.select("a, span.descriptor"):
            desc_text = link.get_text(strip=True).rstrip(",")
            if desc_text:
                descriptors.append(desc_text)
    data["descriptors"] = descriptors

    # Lists count
    data["rym_lists"] = 0
    for info_el in soup.select(".release_stats .stat"):
        label = info_el.get_text(strip=True).lower()
        if "list" in label:
            num_match = re.search(r"(\d[\d,]*)", label)
            if num_match:
                data["rym_lists"] = int(num_match.group(1).replace(",", ""))

    # Rating standard deviation (if available)
    data["rating_std"] = None

    if data["rym_rating"] is None and data["rym_votes"] == 0 and not genres:
        return None

    return data


async def _search_rym_album(
    client: httpx.AsyncClient, artist_name: str, album_title: str,
) -> str | None:
    """Search RYM for an album and return the album page URL if found."""
    query = f"{artist_name} {album_title}"
    search_url = f"{_RYM_BASE}/search?searchterm={quote(query)}&searchtype=l"

    try:
        html = await _rym_get(search_url, client)
    except Exception as e:
        logger.debug(f"RYM search failed for '{query}': {e}")
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Look for first result link
    for link in soup.select(".searchpage a.searchpage"):
        href = link.get("href", "")
        if href.startswith("/release/"):
            return f"{_RYM_BASE}{href}"

    # Alternative selector patterns
    for link in soup.select("a[href^='/release/']"):
        href = link.get("href", "")
        if "/release/" in href:
            return f"{_RYM_BASE}{href}"

    return None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save_rym_album(cur, album_id: str, rym_url: str, data: dict[str, Any]) -> None:
    """Upsert RYM album data."""
    cur.execute(
        """
        INSERT INTO rym_albums (album_id, rym_url, rym_rating, rym_votes, rym_lists,
                                genres, descriptors, rating_std, fetched_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (album_id) DO UPDATE SET
            rym_url = EXCLUDED.rym_url,
            rym_rating = EXCLUDED.rym_rating,
            rym_votes = EXCLUDED.rym_votes,
            rym_lists = EXCLUDED.rym_lists,
            genres = EXCLUDED.genres,
            descriptors = EXCLUDED.descriptors,
            rating_std = EXCLUDED.rating_std,
            fetched_at = EXCLUDED.fetched_at
        """,
        [album_id, rym_url, data.get("rym_rating"), data.get("rym_votes", 0),
         data.get("rym_lists", 0), json.dumps(data.get("genres", [])),
         json.dumps(data.get("descriptors", [])), data.get("rating_std")],
    )

    # Upsert RYM genres into taxonomy table
    for position, genre_name in enumerate(data.get("genres", [])):
        cur.execute(
            "INSERT INTO rym_genres (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id",
            [genre_name],
        )
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT id FROM rym_genres WHERE name = %s", [genre_name])
            row = cur.fetchone()
        if row:
            cur.execute(
                """
                INSERT INTO rym_album_genres (album_id, genre_id, position)
                VALUES (%s, %s, %s)
                ON CONFLICT (album_id, genre_id) DO UPDATE SET position = EXCLUDED.position
                """,
                [album_id, row[0], position],
            )


# ---------------------------------------------------------------------------
# Cult index computation
# ---------------------------------------------------------------------------

def compute_cult_index(rym_rating: float, rym_votes: int, rating_std: float | None) -> float:
    """High rating + low votes + high std dev = cult classic."""
    if rym_votes == 0:
        return 0.0
    quality = rym_rating / 5.0
    obscurity = 1.0 - min(1.0, math.log1p(rym_votes) / math.log1p(5000))
    polarization = min(1.0, (rating_std or 0.0) / 1.5)
    return quality * 0.5 + obscurity * 0.3 + polarization * 0.2


# ---------------------------------------------------------------------------
# Batch pipeline
# ---------------------------------------------------------------------------

async def enrich_albums_from_rym(
    force: bool = False,
    max_albums: int | None = None,
    progress_callback: Any = None,
) -> dict[str, int]:
    """Scrape RateYourMusic for album-level cultural data.

    Args:
        force: Re-scrape albums that already have RYM data.
        max_albums: Limit number of albums to process.
        progress_callback: Optional (current, total, message) callback.

    Returns:
        Stats dict with counts.
    """
    if not settings.rym_scrape_enabled:
        logger.warning("RYM scraping is disabled (set RYM_SCRAPE_ENABLED=true)")
        if progress_callback:
            progress_callback(1, 1, "RYM scraping disabled")
        return {"albums_processed": 0, "albums_matched": 0, "albums_skipped": 0, "errors": 0}

    # Fetch local albums
    with get_connection() as conn:
        with conn.cursor() as cur:
            if force:
                query = """
                    SELECT al.id, al.title, al.year, a.name as artist_name
                    FROM albums al
                    JOIN album_artists aa ON al.id = aa.album_id
                    JOIN artists a ON aa.artist_id = a.id
                    ORDER BY a.name, al.title
                """
            else:
                query = """
                    SELECT al.id, al.title, al.year, a.name as artist_name
                    FROM albums al
                    JOIN album_artists aa ON al.id = aa.album_id
                    JOIN artists a ON aa.artist_id = a.id
                    LEFT JOIN rym_albums ra ON al.id = ra.album_id
                    WHERE ra.album_id IS NULL
                    ORDER BY a.name, al.title
                """
            if max_albums:
                query += f" LIMIT {max_albums}"
            cur.execute(query)
            albums = cur.fetchall()

    stats = {
        "albums_processed": 0,
        "albums_matched": 0,
        "albums_skipped": 0,
        "errors": 0,
    }
    total = len(albums)
    logger.info(f"RYM enrichment: {total} albums to process (force={force})")

    if progress_callback:
        progress_callback(0, total, f"Scraping RYM for {total} albums...")

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, (album_id, title, year, artist_name) in enumerate(albums):
            try:
                rym_url = await _search_rym_album(client, artist_name, title)
                if not rym_url:
                    stats["albums_skipped"] += 1
                    stats["albums_processed"] += 1
                    continue

                html = await _rym_get(rym_url, client)
                data = _parse_album_page(html)

                if data:
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            _save_rym_album(cur, str(album_id), rym_url, data)
                    stats["albums_matched"] += 1
                    logger.debug(
                        f"RYM: '{artist_name} - {title}' → rating={data.get('rym_rating')}, "
                        f"genres={data.get('genres', [])[:3]}"
                    )
                else:
                    stats["albums_skipped"] += 1

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("RYM rate limited — stopping early")
                    stats["errors"] += 1
                    break
                logger.warning(f"RYM HTTP error for '{title}': {e}")
                stats["errors"] += 1
            except Exception as e:
                logger.warning(f"RYM error for '{artist_name} - {title}': {e}")
                stats["errors"] += 1

            stats["albums_processed"] += 1

            if progress_callback and (i + 1) % 5 == 0:
                progress_callback(
                    i + 1, total,
                    f"RYM: {i + 1}/{total} ({stats['albums_matched']} matched)",
                )

            if (i + 1) % 20 == 0:
                logger.info(
                    f"RYM: {i + 1}/{total}, {stats['albums_matched']} matched, "
                    f"{stats['albums_skipped']} skipped"
                )

    if progress_callback:
        progress_callback(total, total, f"RYM complete: {stats['albums_matched']} albums matched")

    logger.info(f"RYM enrichment complete: {stats}")
    return stats
