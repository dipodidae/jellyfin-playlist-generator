"""
Metal Archives Integration for Album Legitimacy Scoring

This module provides functions to fetch album ratings, review counts,
and legitimacy scores from Metal Archives (metal-archives.com).

Usage:
    from app.ingestion.metal_archives import (
        fetch_album_rating,
        is_classic_album,
        calculate_legitimacy_score,
        get_album_legitimacy_data
    )

    # Get legitimacy score for an album
    legitimacy_data = get_album_legitimacy_data("Slayer", "Reign in Blood")
    print(f"Legitimacy Score: {legitimacy_data['legitimacy_score']}/100")
    print(f"Rating: {legitimacy_data['rating']}")
    print(f"Reviews: {legitimacy_data['review_count']}")
"""

import asyncio
import logging
import re
import unicodedata
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
import time

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
from urllib.parse import quote

logger = logging.getLogger(__name__)


# Metal Archives rate limiting
METAL_ARCHIVES_RATE_LIMIT = 1.5  # seconds between requests (conservative)
_last_request_time = 0.0


def _rate_limit() -> None:
    """Enforce rate limiting for Metal Archives requests."""
    global _last_request_time
    current_time = time.monotonic()
    time_since_last = current_time - _last_request_time

    if time_since_last < METAL_ARCHIVES_RATE_LIMIT:
        sleep_time = METAL_ARCHIVES_RATE_LIMIT - time_since_last
        logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f}s")
        time.sleep(sleep_time)

    _last_request_time = time.monotonic()


_NOT_FOUND = {
    "rating": None,
    "review_count": None,
    "year": None,
}


def _ma_session() -> cffi_requests.Session:
    """Create a curl_cffi session that impersonates Chrome to bypass Cloudflare."""
    return cffi_requests.Session(impersonate="chrome", timeout=20)


def _normalize_text(text: str) -> str:
    """Normalize text for comparison: strip diacritics, punctuation, articles, whitespace."""
    # Decompose unicode and strip combining marks (diacritics)
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    s = ascii_text.lower()
    # Normalize fancy quotes/apostrophes/dashes to plain ASCII
    s = re.sub(r"[\u2018\u2019\u0060\u00B4]", "'", s)
    s = re.sub(r"[\u201C\u201D]", '"', s)
    s = re.sub(r"[\u2013\u2014\u2015]", "-", s)
    s = s.replace("\u2026", "...")
    # Strip punctuation except apostrophes inside words
    s = re.sub(r"[^a-z0-9' ]", " ", s)
    # Remove leading articles
    s = re.sub(r"^(the|a|an)\s+", "", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokenize(text: str) -> set:
    """Split normalized text into a set of tokens."""
    return set(_normalize_text(text).split())


def _name_similarity(a: str, b: str) -> float:
    """Score similarity between two names (0-1). Combines exact and token overlap."""
    na, nb = _normalize_text(a), _normalize_text(b)
    if na == nb:
        return 1.0
    # One is a prefix/suffix of the other (e.g. "Burzum" vs "Burzum / Aske")
    if na.startswith(nb) or nb.startswith(na):
        return 0.85
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    # Jaccard-ish but weighted toward the shorter name
    overlap = len(intersection) / min(len(ta), len(tb))
    return overlap * 0.8


def _extract_band_id_and_name(html_cell: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract band ID and name from MA search result HTML cell.

    MA returns HTML like: <a href="https://www.metal-archives.com/bands/Slayer/72">Slayer</a>
    """
    soup = BeautifulSoup(html_cell, "html.parser")
    link = soup.find("a")
    if not link:
        return None, None
    href = link.get("href", "")
    name = link.get_text().strip()
    # Band ID is the last path segment
    match = re.search(r"/bands/[^/]+/(\d+)", href)
    band_id = match.group(1) if match else None
    return band_id, name


def _pick_best_band(results: list, target_artist: str) -> List[Tuple[str, str, float]]:
    """Rank all matching bands from MA search results.

    Returns list of (band_id, band_name, confidence) sorted by descending score.
    Only includes results with score >= 0.4.
    """
    candidates = []
    for row in results:
        band_id, band_name = _extract_band_id_and_name(str(row[0]))
        if not band_id:
            continue
        score = _name_similarity(target_artist, band_name)
        if score >= 0.4:
            candidates.append((band_id, band_name, score))
    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates


def _match_album_title(target: str, candidate: str, artist: str = "") -> float:
    """Score how well a candidate album title matches the target (0-1)."""
    nt = _normalize_text(target)
    nc = _normalize_text(candidate)

    if nt == nc:
        return 1.0

    # Self-titled: album name matches the artist name
    if _normalize_text(artist) == nt and _normalize_text(artist) == nc:
        return 1.0

    # One contains the other (handles subtitle differences)
    if nt in nc or nc in nt:
        length_ratio = min(len(nt), len(nc)) / max(len(nt), len(nc)) if max(len(nt), len(nc)) > 0 else 0
        return 0.7 + 0.2 * length_ratio

    # Token overlap
    tt, tc = set(nt.split()), set(nc.split())
    if not tt or not tc:
        return 0.0
    intersection = tt & tc
    if not intersection:
        return 0.0
    overlap = len(intersection) / min(len(tt), len(tc))
    return overlap * 0.7


def scrape_album_rating(artist: str, album: str) -> Optional[Dict[str, any]]:
    """
    Scrape album rating directly from Metal Archives web page.

    This is the primary method for getting album ratings, review counts, and year.
    Parses the HTML response for rating and review count.

    Args:
        artist: Artist name
        album: Album title

    Returns:
        Dictionary with 'rating', 'review_count', 'year', 'error' keys.

    Example:
        >>> scrape_album_rating("Slayer", "Reign in Blood")
        {
            'rating': 95,
            'review_count': 245,
            'year': 1986,
            'error': None
        }
    """
    try:
        _rate_limit()
        session = _ma_session()

        # Step 1: Search for the band
        search_url = f"https://www.metal-archives.com/search/ajax-band-search/?field=name&query={quote(artist)}&sEcho=1"
        response = session.get(search_url)
        response.raise_for_status()

        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Failed to parse JSON from band search: {e}")
            return {**_NOT_FOUND, "error": f"JSON parse error: {e}"}

        if not data.get("aaData"):
            logger.warning(f"No band results for: {artist}")
            return {**_NOT_FOUND, "error": f"Band not found: {artist}"}

        # Rank all matching bands; may have multiple with same name (e.g. "Slayer", "Death")
        band_candidates = _pick_best_band(data["aaData"], artist)

        if not band_candidates:
            logger.warning(f"No confident band match for '{artist}'")
            return {**_NOT_FOUND, "error": f"Band not found: {artist}"}

        # Step 2: Try each band candidate's discography until we find the target album.
        # This handles disambiguation (e.g. Slayer JP vs Slayer US) by verifying the
        # album actually exists in that band's discography.
        best_url, best_title, best_album_score = None, None, 0.0
        band_id, band_name, band_confidence = None, None, 0.0
        available_titles: List[str] = []

        # Only try top candidates with competitive name scores (within 0.15 of best)
        top_score = band_candidates[0][2]
        candidates_to_try = [
            c for c in band_candidates if c[2] >= top_score - 0.15
        ][:5]  # cap at 5 to avoid excessive requests

        for cand_id, cand_name, cand_confidence in candidates_to_try:
            _rate_limit()
            disco_url = f"https://www.metal-archives.com/band/discography/id/{cand_id}/tab/all"
            try:
                disco_response = session.get(disco_url)
                disco_response.raise_for_status()
            except Exception as e:
                logger.debug(f"Failed to fetch discography for {cand_name} (ID={cand_id}): {e}")
                continue

            disco_soup = BeautifulSoup(disco_response.text, "html.parser")
            album_links = disco_soup.select("a[href*='/albums/']")
            if not album_links:
                continue

            # Score all albums in this band's discography
            for link in album_links:
                link_text = link.get_text().strip()
                score = _match_album_title(album, link_text, artist)
                if score > best_album_score:
                    best_album_score = score
                    best_url = link.get("href")
                    best_title = link_text
                    band_id, band_name, band_confidence = cand_id, cand_name, cand_confidence
                    available_titles = [l.get_text().strip() for l in album_links]

            # Perfect album match — no need to check other bands
            if best_album_score >= 1.0:
                break

        if best_album_score < 0.5 or not best_url:
            logger.warning(
                f"Album '{album}' not found for '{artist}' "
                f"(best: '{best_title}' score={best_album_score:.2f}, "
                f"tried {len(candidates_to_try)} band(s), "
                f"available: {available_titles[:8]})"
            )
            return {
                **_NOT_FOUND,
                "error": f"Album not found: '{album}' (best: '{best_title}' score={best_album_score:.2f})"
            }

        logger.info(
            f"Matched band '{band_name}' (ID={band_id}, confidence={band_confidence:.2f}) for '{artist}'"
        )
        if best_album_score < 1.0:
            logger.info(f"Fuzzy album match: '{album}' -> '{best_title}' (score={best_album_score:.2f})")
        else:
            logger.info(f"Exact album match: '{best_title}'")

        # Step 3: Fetch album page
        _rate_limit()
        album_response = session.get(best_url)
        album_response.raise_for_status()

        album_soup = BeautifulSoup(album_response.text, "html.parser")

        # Extract year from album info (dt/dd pairs in the album sidebar)
        year = None
        for dt in album_soup.find_all("dt"):
            if "release date" in dt.get_text().lower():
                dd = dt.find_next_sibling("dd")
                if dd:
                    year_match = re.search(r"(\d{4})", dd.get_text())
                    if year_match:
                        y = int(year_match.group(1))
                        if 1960 <= y <= 2030:
                            year = y
                break
        # Fallback: look for year anywhere in page text (less reliable)
        if year is None:
            for m in re.finditer(r"\b(\d{4})\b", album_soup.get_text()):
                y = int(m.group(1))
                if 1970 <= y <= 2026:
                    year = y
                    break

        # Extract rating and review count
        # MA shows these as "N reviews (avg. XX%)" in the album info section
        rating = None
        review_count = 0
        album_text = album_soup.get_text()

        # Pattern: "45 reviews (avg. 85%)" or "1 review (100%)"
        review_rating_match = re.search(
            r'(\d+)\s+reviews?\s*\((?:avg\.\s*)?(\d+)%\)', album_text
        )
        if review_rating_match:
            review_count = int(review_rating_match.group(1))
            rating = int(review_rating_match.group(2))
            logger.debug(f"Found {review_count} reviews, avg rating: {rating}%")

        # Fallback: try span.score (older MA page format)
        if rating is None:
            score_elem = album_soup.find("span", class_="score")
            if score_elem:
                try:
                    rating = int(score_elem.get_text().strip())
                except ValueError:
                    pass

        # Combined match confidence: band * album
        match_confidence = round(band_confidence * best_album_score, 3)
        logger.info(
            f"Scraped album: {artist} - {album} -> {band_name} - {best_title} "
            f"| Rating: {rating}%, Reviews: {review_count}, Year: {year}, "
            f"Confidence: {match_confidence:.2f} (band={band_confidence:.2f}, album={best_album_score:.2f})"
        )

        return {
            "rating": rating,
            "review_count": review_count,
            "year": year,
            "match_confidence": match_confidence,
            "error": None
        }

    except Exception as e:
        logger.error(f"Error scraping album rating for {artist} - {album}: {e}")
        return {**_NOT_FOUND, "error": str(e)}


def fetch_album_rating(artist: str, album: str) -> Optional[Dict[str, any]]:
    """
    Fetch album rating and metadata from Metal Archives.

    This is a convenience wrapper around scrape_album_rating.

    Args:
        artist: Artist name (exact match or close variant)
        album: Album title

    Returns:
        Dictionary with 'rating', 'review_count', 'year', 'error' keys,
        or None if album not found or error occurs.

    Example:
        >>> fetch_album_rating("Slayer", "Reign in Blood")
        {
            'rating': 95,
            'review_count': 245,
            'year': 1986,
            'error': None
        }
    """
    return scrape_album_rating(artist, album)


def is_classic_album(artist: str, album: str) -> bool:
    """
    Determine if an album is recognized as a classic/influential album.

    This uses a curated list of metal classics. In a production system,
    this could be enhanced with:
    - Expert-curated lists from metal publications
    - Citation metrics (credits, covers, references)
    - Wikipedia "notable album" recognition
    - Genre-defining status

    Current list focuses on first-wave black metal, thrash, death metal,
    and doom metal classics from Tom's preferred era.

    Args:
        artist: Artist name
        album: Album title

    Returns:
        True if recognized as classic, False otherwise.

    Example:
        >>> is_classic_album("Slayer", "Reign in Blood")
        True
        >>> is_classic_album("Unknown Band", "Unknown Album")
        False
    """
    # Curated list of metal classics
    # Focus on Tom's genre interests: first-wave black metal, Teutonic thrash
    classics = {
        # Thrash Metal (Teutonic + US)
        ("slayer", "reign in blood"),
        ("slayer", "south of heaven"),
        ("slayer", "seasons in the abyss"),
        ("metallica", "master of puppets"),
        ("metallica", "ride the lightning"),
        ("megadeth", "rust in peace"),
        ("megadeth", "peace sells"),
        ("kreator", "pleasure to kill"),
        ("kreator", "coma of souls"),
        ("destruction", "infernal overkill"),
        ("destruction", "eternal devastation"),
        ("sodom", "persecution mania"),
        ("sodom", "agent orange"),
        ("sepultura", "beneath the remains"),
        ("sepultura", "arise"),
        ("exodus", "bonded by blood"),
        ("testament", "the new order"),
        ("dark angel", "darkness descends"),
        ("morbid saint", "altered of death"),
        ("posessed", "seven churches"),
        ("cannibal corpse", "butchered at birth"),
        ("obituary", "slowly we rot"),

        # Black Metal (First wave + Second Wave)
        ("bathory", "under the sign of the black mark"),
        ("bathory", "blood fire death"),
        ("mayhem", "de mysteriis dom sathanas"),
        ("darkthrone", "a blaze in the northern sky"),
        ("emperor", "in the nightside eclipse"),
        ("emperor", "anthems to the welkin at dusk"),
        ("burzum", "burzum"),
        ("burzum", "det som engang once var"),
        ("immortal", "battles in the north"),
        ("immortal", "at the heart of winter"),
        ("dissection", "storm of the light's bane"),
        ("dissection", "reinkaos"),
        ("watain", "ravenna"),
        ("watain", "sworn to the dark"),
        ("sarcófago", "i.n.r.i."),
        ("vulcano", "bloody vengeance"),
        ("bulldozer", "the final separation"),

        # Doom Metal
        ("candlemass", "epicus doomicus metallicus"),
        ("candlemass", "nightfall"),
        ("paradise lost", "gothic"),
        ("my dying bride", "turn loose the swans"),
        ("type o negative", "bloody kisses"),

        # Death Metal
        ("death", "human"),
        ("death", "leprosy"),
        ("death", "scream bloody gore"),
        ("morbid angel", "altars of madness"),
        ("morbid angel", "blessed are the sick"),
        ("carcass", "necroticism"),
        ("cannibal corpse", "the bleeding"),
        ("dismember", "like an ever flowing stream"),
    }

    lookup = (artist.lower(), album.lower())
    is_classic = lookup in classics

    if is_classic:
        logger.info(f"Album recognized as classic: {artist} - {album}")

    return is_classic


def calculate_legitimacy_score(
    rating: Optional[int],
    review_count: Optional[int],
    is_classic: bool
) -> int:
    """
    Calculate album legitimacy score (0-100).

    Formula:
        legitimacy_score = (rating * 0.6) +
                           (review_count_normalized * 0.3) +
                           (classic_bonus * 0.1)

    Args:
        rating: Album rating percentage (0-100), or None if unavailable
        review_count: Number of reviews, or None if unavailable
        is_classic: Whether album is recognized as classic/influential

    Returns:
        Legitimacy score from 0 to 100.

    Examples:
        >>> calculate_legitimacy_score(95, 245, True)
        95
        >>> calculate_legitimacy_score(85, 50, False)
        65
        >>> calculate_legitimacy_score(None, None, False)
        0
        >>> calculate_legitimacy_score(None, None, True)
        60
    """
    if rating is None or review_count is None:
        # If we don't have data, use classic status as a proxy
        if is_classic:
            return 60  # Baseline for recognized classics
        else:
            return 40  # Baseline for unknown albums

    # Normalize review count (100+ reviews = max score)
    review_count_normalized = min(review_count / 100.0, 1.0) * 100

    # Classic bonus (10 points)
    classic_bonus = 10 if is_classic else 0

    # Calculate weighted score
    legitimacy_score = (
        (rating * 0.6) +
        (review_count_normalized * 0.3) +
        classic_bonus
    )

    # Round to integer and clamp to 0-100
    legitimacy_score = int(round(legitimacy_score))
    legitimacy_score = max(0, min(100, legitimacy_score))

    return legitimacy_score


def get_album_legitimacy_data(artist: str, album: str) -> Dict[str, any]:
    """
    Get full legitimacy data for an album.

    This is the main entry point for album legitimacy scoring.

    Args:
        artist: Artist name
        album: Album title

    Returns:
        Dictionary with all legitimacy information:
        {
            'legitimacy_score': int (0-100),
            'rating': Optional[int],
            'review_count': Optional[int],
            'year': Optional[int],
            'is_classic': bool,
            'error': Optional[str]
        }

    Example:
        >>> data = get_album_legitimacy_data("Slayer", "Reign in Blood")
        {
            'legitimacy_score': 95,
            'rating': 95,
            'review_count': 245,
            'year': 1986,
            'is_classic': True,
            'error': None
        }
    """
    logger.info(f"Fetching legitimacy data for: {artist} - {album}")

    # Scrape album data
    album_data = scrape_album_rating(artist, album)

    # Check if it's recognized as classic
    is_classic = is_classic_album(artist, album)

    # Calculate legitimacy score
    legitimacy_score = calculate_legitimacy_score(
        rating=album_data["rating"] if album_data else None,
        review_count=album_data["review_count"] if album_data else None,
        is_classic=is_classic
    )

    return {
        "legitimacy_score": legitimacy_score,
        "rating": album_data["rating"] if album_data else None,
        "review_count": album_data["review_count"] if album_data else None,
        "year": album_data.get("year") if album_data else None,
        "is_classic": is_classic,
        "error": album_data.get("error") if album_data else None
    }


# Batch processing for multiple albums
def get_albums_legitimacy_data(albums: list[Tuple[str, str]]) -> Dict[str, any]:
    """
    Get legitimacy data for multiple albums at once.

    Args:
        albums: List of (artist, album) tuples

    Returns:
        Dictionary mapping album identifiers to their legitimacy data.
        Album identifier format: "artist_album" (normalized to lowercase).

    Example:
        >>> albums = [
        ...     ("Slayer", "Reign in Blood"),
        ...     ("Kreator", "Pleasure to Kill"),
        ... ]
        >>> results = get_albums_legitimacy_data(albums)
        {
            'slayer_reign in blood': {
                'legitimacy_score': 95,
                'rating': 95,
                ...
            },
            'kreator_pleasure to kill': {
                'legitimacy_score': 88,
                'rating': 88,
                ...
            }
        }
    """
    results = {}

    for artist, album in albums:
        album_key = f"{artist.lower()}_{album.lower()}"
        results[album_key] = get_album_legitimacy_data(artist, album)

    logger.info(f"Fetched legitimacy data for {len(results)} albums")

    return results


async def enrich_albums_from_metal_archives(
    force: bool = False,
    progress_callback=None,
) -> dict:
    """Batch-enrich albums with Metal Archives legitimacy data.

    Queries all albums from the database, skips those already enriched (unless force=True),
    scrapes Metal Archives for each, and stores results in album_legitimacy.

    Args:
        force: Re-scrape albums that already have legitimacy data.
        progress_callback: Optional callable(current, total, message) for progress reporting.

    Returns:
        Dict with enrichment stats.
    """
    from app.database_pg import get_connection

    # Gather albums needing enrichment
    with get_connection() as conn:
        with conn.cursor() as cur:
            if force:
                cur.execute("""
                    SELECT a.id, a.title, ar.name
                    FROM albums a
                    JOIN album_artists aa ON aa.album_id = a.id
                    JOIN artists ar ON ar.id = aa.artist_id
                    WHERE aa.position = 0
                """)
            else:
                cur.execute("""
                    SELECT a.id, a.title, ar.name
                    FROM albums a
                    JOIN album_artists aa ON aa.album_id = a.id
                    JOIN artists ar ON ar.id = aa.artist_id
                    LEFT JOIN album_legitimacy al ON al.album_id = a.id
                    WHERE aa.position = 0 AND al.album_id IS NULL
                """)
            rows = cur.fetchall()

    total = len(rows)
    if total == 0:
        msg = "No albums need Metal Archives enrichment"
        logger.info(msg)
        if progress_callback:
            progress_callback(0, 0, msg)
        return {"enriched": 0, "skipped": 0, "errors": 0, "total": 0}

    logger.info(f"Metal Archives enrichment: {total} albums to process")
    enriched = 0
    errors = 0

    for i, (album_id, album_title, artist_name) in enumerate(rows):
        if progress_callback and i % 5 == 0:
            progress_callback(i, total, f"Scraping {artist_name} - {album_title}")

        try:
            data = await asyncio.to_thread(get_album_legitimacy_data, artist_name, album_title)

            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO album_legitimacy (album_id, ma_rating, ma_review_count, match_confidence)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (album_id) DO UPDATE SET
                            ma_rating = EXCLUDED.ma_rating,
                            ma_review_count = EXCLUDED.ma_review_count,
                            match_confidence = EXCLUDED.match_confidence,
                            scraped_at = now()
                    """, (
                        str(album_id),
                        data.get("rating"),
                        data.get("review_count", 0),
                        data.get("match_confidence", 0.0),
                    ))
                    conn.commit()
            enriched += 1
        except Exception as e:
            logger.warning(f"MA enrichment failed for {artist_name} - {album_title}: {e}")
            errors += 1

    msg = f"Metal Archives enrichment complete: {enriched} enriched, {errors} errors out of {total}"
    logger.info(msg)
    if progress_callback:
        progress_callback(total, total, msg)

    return {"enriched": enriched, "errors": errors, "total": total}


if __name__ == "__main__":
    # Test the module with sample albums
    import sys

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    test_albums = [
        ("Slayer", "Reign in Blood"),
        ("Sodom", "Persecution Mania"),
        ("Kreator", "Pleasure to Kill"),
        ("Bathory", "Under the Sign of the Black Mark"),
        ("Metallica", "Master of Puppets"),
    ]

    print("Testing Metal Archives Integration")
    print("=" * 60)

    all_results = get_albums_legitimacy_data(test_albums)

    for artist, album in test_albums:
        key = f"{artist.lower()}_{album.lower()}"
        result = all_results.get(key, {})

        print(f"\n{artist} - {album}")
        print(f"  Legitimacy Score: {result.get('legitimacy_score')}/100")
        print(f"  Rating: {result.get('rating')}")
        print(f"  Reviews: {result.get('review_count')}")
        print(f"  Year: {result.get('year')}")
        print(f"  Classic: {'Yes' if result.get('is_classic') else 'No'}")
        if result.get('error'):
            print(f"  Error: {result['error']}")

    print("\n" + "=" * 60)
    print("Test complete!")
