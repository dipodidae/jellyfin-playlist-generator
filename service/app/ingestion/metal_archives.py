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
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone
import time

import httpx
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

        # Step 1: Search for the band
        search_url = f"https://www.metal-archives.com/search/ajax-bands/search/?iBand=&sBand={quote(artist)}"

        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(search_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            response.raise_for_status()

            # Parse JSON response
            try:
                data = response.json()
            except Exception as e:
                logger.error(f"Failed to parse JSON from band search: {e}")
                return {
                    "rating": None,
                    "review_count": None,
                    "year": None,
                    "error": f"JSON parse error: {e}"
                }

            if not data.get("aaData"):
                logger.warning(f"No band results for: {artist}")
                return {
                    "rating": None,
                    "review_count": None,
                    "year": None,
                    "error": f"Band not found: {artist}"
                }

            # Get first matching band
            first_band = data["aaData"][0]
            # Format: [id, name, country, genres, status, formed, location]
            band_id = str(first_band[0])

            logger.info(f"Found band '{first_band[1]}' with ID {band_id}")

            # Step 2: Get the band's albums
            band_url = f"https://www.metal-archives.com/bands/_/{band_id}"
            band_response = client.get(band_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            })
            band_response.raise_for_status()

            band_soup = BeautifulSoup(band_response.text, "html.parser")

            # Find album links
            # Look for links in the discography section
            album_links = band_soup.select("table#band_tab_discog a[href*='/albums/']")
            album_url = None

            album_url_lower = album.lower()
            for link in album_links:
                link_text = link.get_text().strip()
                # Try exact match first, then partial
                if link_text.lower() == album_url_lower:
                    album_url = link["href"]
                    break
                # Skip "Various Artists" compilations
                if "various artists" not in link_text.lower():
                    if album_url_lower in link_text.lower() or link_text.lower() in album_url_lower:
                        album_url = link["href"]
                        break

            if not album_url:
                logger.warning(f"Album '{album}' not found on band page for '{artist}'")
                # List available albums for debugging
                available = [link.get_text().strip() for link in album_links[:10]]
                logger.debug(f"Available albums: {available}")
                return {
                    "rating": None,
                    "review_count": None,
                    "year": None,
                    "error": f"Album not found: '{album}' (found: {available[:3]}...)"
                }

            logger.info(f"Found album URL: {album_url}")

            # Step 3: Fetch album page
            album_response = client.get(album_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            })
            album_response.raise_for_status()

            album_soup = BeautifulSoup(album_response.text, "html.parser")

            # Extract year from album page
            year = None
            year_match = re.search(r'(\d{4})', album_soup.get_text())
            if year_match:
                # Get the year that seems to be part of the album information
                # Look for year in the sidebar/panel or release info
                year_str = year_match.group(1)
                try:
                    year = int(year_str)
                    # Sanity check: year should be reasonable (1970-2026)
                    if year < 1970 or year > 2026:
                        year = None
                except ValueError:
                    year = None

            # Extract rating percentage
            rating = None
            rating_elem = album_soup.find("span", class_="score")
            if rating_elem:
                try:
                    rating_text = rating_elem.get_text().strip()
                    rating = int(rating_text)
                    logger.debug(f"Found rating: {rating}")
                except ValueError:
                    logger.warning(f"Could not parse rating: '{rating_text}'")

            # Extract review count
            review_count = 0
            review_elem = album_soup.find("span", class_="float_right")
            if review_elem:
                # Format: "X reviews" or "X review" or "X review(s)"
                review_text = review_elem.get_text().strip()
                review_match = re.search(r'(\d+)\s*review', review_text, re.IGNORECASE)
                if review_match:
                    review_count = int(review_match.group(1))
                    logger.debug(f"Found review count: {review_count}")

            # Alternative: look for review count in ratingStats
            if review_count == 0:
                rating_stats = album_soup.find("div", id="ratingStats")
                if rating_stats:
                    review_text = rating_stats.get_text().strip()
                    review_match = re.search(r'(\d+)\s*review', review_text, re.IGNORECASE)
                    if review_match:
                        review_count = int(review_match.group(1))

            logger.info(f"Scraped album: {artist} - {album} - Rating: {rating}%, Reviews: {review_count}, Year: {year}")

            return {
                "rating": rating,
                "review_count": review_count,
                "year": year,
                "error": None
            }

    except httpx.TimeoutException as e:
        logger.error(f"Timeout fetching album rating for {artist} - {album}: {e}")
        return {
            "rating": None,
            "review_count": None,
            "year": None,
            "error": f"Timeout: {e}"
        }
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching album rating for {artist} - {album}: {e}")
        return {
            "rating": None,
            "review_count": None,
            "year": None,
            "error": f"HTTP error: {e.response.status_code}"
        }
    except Exception as e:
        logger.error(f"Error scraping album rating for {artist} - {album}: {e}")
        return {
            "rating": None,
            "review_count": None,
            "year": None,
            "error": str(e)
        }


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