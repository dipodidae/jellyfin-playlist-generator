"""Discogs API client for original release date resolution.

Uses the Discogs REST API (token auth, 60 req/min) to find master releases
and extract the true original release year. Master releases in Discogs
represent the canonical "first pressing" concept — exactly what we need.

Priority: physical chronology anchor (most reliable for first pressings).
"""

import asyncio
import logging
import re
from difflib import SequenceMatcher
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_DISCOGS_BASE = "https://api.discogs.com"
_UA = "playlist-generator/1.0"

# Reissue indicators to filter out from title matching
_REISSUE_PATTERNS = re.compile(
    r"\s*[\(\[]?\s*("
    r"remaster(?:ed)?|reissue|re-?issue|anniversary\s*edition|"
    r"deluxe\s*edition|expanded\s*edition|bonus\s*tracks?|"
    r"special\s*edition|limited\s*edition|collector'?s?\s*edition|"
    r"digipak|slipcase|box\s*set|compilation|"
    r"\d+th\s*anniversary|re-?press|"
    r"vinyl\s*reissue|cd\s*reissue"
    r")\s*[\)\]]?\s*",
    re.IGNORECASE,
)


def _normalize_title(title: str) -> str:
    """Strip reissue noise from album title for matching."""
    cleaned = _REISSUE_PATTERNS.sub("", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).lower().strip()
    return cleaned


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio()


async def _discogs_get(
    path: str,
    client: httpx.AsyncClient,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Make a Discogs API request with auth and rate limiting."""
    if not settings.discogs_token:
        return None

    url = f"{_DISCOGS_BASE}{path}"
    headers = {
        "Authorization": f"Discogs token={settings.discogs_token}",
        "User-Agent": _UA,
    }

    try:
        resp = await client.get(url, headers=headers, params=params or {})
        if resp.status_code == 429:
            # Rate limited — back off
            retry_after = int(resp.headers.get("Retry-After", "60"))
            logger.warning(f"Discogs rate limited, waiting {retry_after}s")
            await asyncio.sleep(retry_after)
            resp = await client.get(url, headers=headers, params=params or {})
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        logger.debug(f"Discogs HTTP error: {e.response.status_code} for {path}")
        return None
    except Exception as e:
        logger.debug(f"Discogs request failed: {e}")
        return None


async def search_master_release(
    client: httpx.AsyncClient,
    artist_name: str,
    album_title: str,
    year_hint: int | None = None,
) -> dict[str, Any] | None:
    """Search Discogs for a master release matching artist + album.

    Returns dict with: master_id, year, title, country, label, format,
    catalog_number, confidence.
    """
    data = await _discogs_get("/database/search", client, params={
        "type": "master",
        "artist": artist_name,
        "release_title": album_title,
        "per_page": 10,
    })

    if not data or not data.get("results"):
        # Fallback: broader search
        data = await _discogs_get("/database/search", client, params={
            "type": "master",
            "q": f"{artist_name} {album_title}",
            "per_page": 10,
        })

    if not data or not data.get("results"):
        return None

    best = None
    best_score = 0.0

    for result in data["results"]:
        result_title = result.get("title", "")
        # Discogs format: "Artist - Title"
        if " - " in result_title:
            _, result_album = result_title.split(" - ", 1)
        else:
            result_album = result_title

        title_sim = _title_similarity(album_title, result_album)

        # Year proximity bonus
        result_year = result.get("year")
        year_score = 0.5
        if year_hint and result_year:
            try:
                diff = abs(year_hint - int(result_year))
                if diff == 0:
                    year_score = 1.0
                elif diff == 1:
                    year_score = 0.8
                elif diff <= 3:
                    year_score = 0.5
                else:
                    year_score = 0.1
            except (ValueError, TypeError):
                pass

        combined = title_sim * 0.55 + year_score * 0.30 + 0.15  # base for being a result
        if combined > best_score:
            best_score = combined
            best = {
                "master_id": result.get("master_id") or result.get("id"),
                "year": int(result_year) if result_year else None,
                "title": result_album,
                "country": result.get("country"),
                "label": (result.get("label") or [""])[0] if result.get("label") else None,
                "format": (result.get("format") or [""])[0] if result.get("format") else None,
                "catalog_number": result.get("catno"),
                "confidence": combined,
                "resource_url": result.get("resource_url"),
            }

    if best and best["confidence"] >= 0.55:
        return best
    return None


async def get_master_release_details(
    client: httpx.AsyncClient,
    master_id: int,
) -> dict[str, Any] | None:
    """Fetch master release details to get the authoritative original year.

    The master release `year` field in Discogs represents the original
    release year — this is the canonical first-pressing date.
    """
    data = await _discogs_get(f"/masters/{master_id}", client)
    if not data:
        return None

    return {
        "master_id": master_id,
        "year": data.get("year"),
        "title": data.get("title"),
        "artists": [a.get("name", "") for a in data.get("artists", [])],
        "genres": data.get("genres", []),
        "styles": data.get("styles", []),
        "main_release_id": data.get("main_release"),
        "num_versions": data.get("versions_count", 0),
    }


async def get_earliest_release(
    client: httpx.AsyncClient,
    master_id: int,
) -> dict[str, Any] | None:
    """Fetch the earliest release version of a master to get detailed
    first-pressing info (country, label, format, catalog number).

    Sorted by year ascending — first result is the earliest pressing.
    """
    data = await _discogs_get(f"/masters/{master_id}/versions", client, params={
        "sort": "released",
        "sort_order": "asc",
        "per_page": 5,
    })

    if not data or not data.get("versions"):
        return None

    for version in data["versions"]:
        title = version.get("title", "").lower()
        # Skip obvious reissues
        if any(tag in title for tag in ["remaster", "reissue", "deluxe", "anniversary"]):
            continue

        year = None
        released = version.get("released")
        if released and len(released) >= 4:
            try:
                year = int(released[:4])
            except ValueError:
                pass

        if year:
            month = None
            day = None
            if released and len(released) >= 7:
                try:
                    month = int(released[5:7])
                except ValueError:
                    pass
            if released and len(released) >= 10:
                try:
                    day = int(released[8:10])
                except ValueError:
                    pass

            return {
                "year": year,
                "month": month if month and 1 <= month <= 12 else None,
                "day": day if day and 1 <= day <= 31 else None,
                "country": version.get("country"),
                "label": version.get("label"),
                "format": version.get("major_formats", [""])[0] if version.get("major_formats") else None,
                "catalog_number": version.get("catno"),
            }

    return None


async def resolve_discogs_release_date(
    client: httpx.AsyncClient,
    artist_name: str,
    album_title: str,
    year_hint: int | None = None,
) -> dict[str, Any] | None:
    """Full Discogs resolution pipeline for an album.

    1. Search for master release
    2. Get master details (original year)
    3. Get earliest release version (detailed first-pressing info)

    Returns combined result or None.
    """
    # Rate limit: ~1 req/sec to stay well under 60/min
    await asyncio.sleep(1.1)

    search_result = await search_master_release(client, artist_name, album_title, year_hint)
    if not search_result or not search_result.get("master_id"):
        return None

    master_id = search_result["master_id"]

    # Get master details for authoritative year
    await asyncio.sleep(1.1)
    master = await get_master_release_details(client, master_id)

    # Get earliest release for detailed info
    await asyncio.sleep(1.1)
    earliest = await get_earliest_release(client, master_id)

    # Build combined result
    result: dict[str, Any] = {
        "source": "discogs",
        "master_id": master_id,
        "confidence": search_result["confidence"],
    }

    # Prefer master year (authoritative), fall back to earliest release
    if master and master.get("year"):
        result["year"] = master["year"]
    elif earliest and earliest.get("year"):
        result["year"] = earliest["year"]
    elif search_result.get("year"):
        result["year"] = search_result["year"]
    else:
        return None

    # Detailed first-pressing info from earliest release
    if earliest:
        result["month"] = earliest.get("month")
        result["day"] = earliest.get("day")
        result["country"] = earliest.get("country")
        result["label"] = earliest.get("label")
        result["format"] = earliest.get("format")
        result["catalog_number"] = earliest.get("catalog_number")
    else:
        result["month"] = None
        result["day"] = None
        result["country"] = search_result.get("country")
        result["label"] = search_result.get("label")
        result["format"] = search_result.get("format")
        result["catalog_number"] = search_result.get("catalog_number")

    # Determine precision
    if result.get("day"):
        result["precision"] = "day"
    elif result.get("month"):
        result["precision"] = "month"
    else:
        result["precision"] = "year"

    return result
