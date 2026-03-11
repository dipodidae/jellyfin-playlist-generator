import asyncio
import logging
from typing import Any

import pylast

from app.config import settings
from app.database_pg import get_connection

logger = logging.getLogger(__name__)


def get_lastfm_network() -> pylast.LastFMNetwork:
    if not settings.lastfm_api_key:
        raise ValueError("Last.fm API key must be configured")

    return pylast.LastFMNetwork(
        api_key=settings.lastfm_api_key,
        api_secret=settings.lastfm_api_secret,
    )


async def fetch_artist_tags(network: pylast.LastFMNetwork, artist_name: str) -> list[dict[str, Any]]:
    """Fetch top tags for an artist from Last.fm."""
    try:
        artist = network.get_artist(artist_name)
        top_tags = await asyncio.to_thread(artist.get_top_tags, limit=10)
        return [{"name": tag.item.name.lower(), "weight": int(tag.weight)} for tag in top_tags]
    except pylast.WSError as e:
        if "Artist not found" in str(e):
            logger.debug(f"Artist not found on Last.fm: {artist_name}")
        else:
            logger.warning(f"Last.fm error for artist {artist_name}: {e}")
        return []
    except Exception as e:
        logger.warning(f"Error fetching tags for artist {artist_name}: {e}")
        return []


async def fetch_track_tags(
    network: pylast.LastFMNetwork, artist_name: str, track_title: str
) -> list[dict[str, Any]]:
    """Fetch top tags for a track from Last.fm."""
    try:
        track = network.get_track(artist_name, track_title)
        top_tags = await asyncio.to_thread(track.get_top_tags, limit=10)
        return [{"name": tag.item.name.lower(), "weight": int(tag.weight)} for tag in top_tags]
    except pylast.WSError as e:
        if "Track not found" in str(e):
            logger.debug(f"Track not found on Last.fm: {artist_name} - {track_title}")
        else:
            logger.warning(f"Last.fm error for track {artist_name} - {track_title}: {e}")
        return []
    except Exception as e:
        logger.warning(f"Error fetching tags for track {artist_name} - {track_title}: {e}")
        return []


async def fetch_similar_artists(
    network: pylast.LastFMNetwork, artist_name: str
) -> list[dict[str, Any]]:
    """Fetch similar artists from Last.fm."""
    try:
        artist = network.get_artist(artist_name)
        similar = await asyncio.to_thread(artist.get_similar, limit=20)
        return [
            {"name": sim_artist.item.name, "match": float(sim_artist.match)}
            for sim_artist in similar
        ]
    except pylast.WSError as e:
        if "Artist not found" in str(e):
            logger.debug(f"Artist not found on Last.fm: {artist_name}")
        else:
            logger.warning(f"Last.fm error for similar artists {artist_name}: {e}")
        return []
    except Exception as e:
        logger.warning(f"Error fetching similar artists for {artist_name}: {e}")
        return []


async def fetch_track_stats(
    network: pylast.LastFMNetwork, artist_name: str, track_title: str
) -> dict[str, int] | None:
    """Fetch playcount and listener count for a track."""
    try:
        track = network.get_track(artist_name, track_title)
        playcount = await asyncio.to_thread(track.get_playcount)
        listener_count = await asyncio.to_thread(track.get_listener_count)
        return {"playcount": playcount or 0, "listeners": listener_count or 0}
    except Exception as e:
        logger.debug(f"Error fetching stats for {artist_name} - {track_title}: {e}")
        return None


def upsert_lastfm_tag(cur, tag_name: str) -> int:
    """Insert or get existing Last.fm tag, return tag_id."""
    cur.execute(
        "SELECT id FROM lastfm_tags WHERE name = %s", [tag_name]
    )
    result = cur.fetchone()
    if result:
        return result[0]

    cur.execute(
        "INSERT INTO lastfm_tags (name) VALUES (%s) RETURNING id",
        [tag_name]
    )
    return cur.fetchone()[0]


def save_track_tags(cur, track_id: str, tags: list[dict[str, Any]]) -> int:
    """Save track tags to database."""
    saved = 0
    for tag in tags:
        tag_id = upsert_lastfm_tag(cur, tag["name"])
        cur.execute(
            """
            INSERT INTO track_lastfm_tags (track_id, tag_id, weight)
            VALUES (%s, %s, %s)
            ON CONFLICT (track_id, tag_id) DO UPDATE SET weight = excluded.weight
            """,
            [track_id, tag_id, tag["weight"]],
        )
        saved += 1
    return saved


def save_artist_tags(cur, artist_id: str, tags: list[dict[str, Any]]) -> int:
    """Save artist tags to database."""
    saved = 0
    for tag in tags:
        tag_id = upsert_lastfm_tag(cur, tag["name"])
        cur.execute(
            """
            INSERT INTO artist_lastfm_tags (artist_id, tag_id, weight)
            VALUES (%s, %s, %s)
            ON CONFLICT (artist_id, tag_id) DO UPDATE SET weight = excluded.weight
            """,
            [artist_id, tag_id, tag["weight"]],
        )
        saved += 1
    return saved


def save_artist_similarity(cur, artist_id: str, similar_artists: list[dict[str, Any]]) -> int:
    """Save artist similarity relationships to database."""
    saved = 0
    for similar in similar_artists:
        cur.execute(
            "SELECT id FROM artists WHERE name = %s", [similar["name"]]
        )
        similar_result = cur.fetchone()

        if similar_result:
            similar_artist_id = similar_result[0]
            cur.execute(
                """
                INSERT INTO artist_similarity (artist_id, similar_artist_id, similarity)
                VALUES (%s, %s, %s)
                ON CONFLICT (artist_id, similar_artist_id) DO UPDATE SET similarity = excluded.similarity
                """,
                [artist_id, similar_artist_id, similar["match"]],
            )
            saved += 1
    return saved


def save_track_stats(cur, track_id: str, stats: dict[str, int]) -> None:
    """Save Last.fm stats for a track."""
    cur.execute(
        """
        INSERT INTO lastfm_stats (track_id, playcount, listeners, fetched_at)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (track_id) DO UPDATE SET
            playcount = excluded.playcount,
            listeners = excluded.listeners,
            fetched_at = excluded.fetched_at
        """,
        [track_id, stats["playcount"], stats["listeners"]],
    )


def persist_artist_enrichment(
    artist_id: str,
    tags: list[dict[str, Any]],
    similar_artists: list[dict[str, Any]],
) -> tuple[int, int]:
    tags_added = 0
    similarities_added = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            if tags:
                tags_added = save_artist_tags(cur, artist_id, tags)
            if similar_artists:
                similarities_added = save_artist_similarity(cur, artist_id, similar_artists)
    return tags_added, similarities_added


def persist_track_enrichment(
    track_id: str,
    tags: list[dict[str, Any]],
    track_stats_data: dict[str, int] | None,
) -> tuple[int, int]:
    tags_added = 0
    stats_added = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            if tags:
                tags_added = save_track_tags(cur, track_id, tags)
            if track_stats_data:
                save_track_stats(cur, track_id, track_stats_data)
                stats_added = 1
    return tags_added, stats_added


async def enrich_artists_from_lastfm(
    batch_size: int = 50,
    delay_between_requests: float = 0.2,
    progress_callback: Any = None,
) -> dict[str, int]:
    """Fetch tags and similar artists for all artists in the database."""
    network = get_lastfm_network()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.name
                FROM artists a
                LEFT JOIN artist_lastfm_tags alt ON a.id = alt.artist_id
                WHERE alt.artist_id IS NULL
                ORDER BY (
                    SELECT COUNT(*) FROM track_artists ta WHERE ta.artist_id = a.id
                ) DESC
            """)
            artists = cur.fetchall()

    stats: dict[str, int] = {"artists_processed": 0, "tags_added": 0, "similarities_added": 0}
    total = len(artists)
    logger.info(f"Enriching {total} artists from Last.fm")

    for i, (artist_id, artist_name) in enumerate(artists):
        tags = await fetch_artist_tags(network, artist_name)
        similar = await fetch_similar_artists(network, artist_name)

        tags_added, similarities_added = persist_artist_enrichment(str(artist_id), tags, similar)
        stats["tags_added"] += tags_added
        stats["similarities_added"] += similarities_added
        stats["artists_processed"] += 1

        if progress_callback and (i + 1) % 10 == 0:
            pct = int(((i + 1) / total) * 100)
            progress_callback(i + 1, total, f"Enriched {i + 1}/{total} artists")

        if (i + 1) % 50 == 0:
            logger.info(f"Enriched {i + 1}/{total} artists (saved to DB)")

        await asyncio.sleep(delay_between_requests)

    if progress_callback:
        progress_callback(total, total, f"Last.fm enrichment complete: {total} artists processed")

    return stats


async def enrich_tracks_from_lastfm(
    batch_size: int = 100,
    delay_between_requests: float = 0.2,
    max_tracks: int | None = None,
    progress_callback: Any = None,
) -> dict[str, int]:
    """Fetch tags for tracks from Last.fm. Prioritizes tracks without tags."""
    network = get_lastfm_network()

    query = """
        SELECT t.id, t.title, a.name as artist_name
        FROM tracks t
        LEFT JOIN track_artists ta ON ta.track_id = t.id AND ta.role = 'primary'
        LEFT JOIN artists a ON ta.artist_id = a.id
        LEFT JOIN track_lastfm_tags tlt ON t.id = tlt.track_id
        WHERE tlt.track_id IS NULL
        ORDER BY RANDOM()
    """
    if max_tracks:
        query += f" LIMIT {max_tracks}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            tracks = cur.fetchall()

    stats: dict[str, int] = {"tracks_processed": 0, "tags_added": 0, "stats_added": 0}
    total = len(tracks)
    logger.info(f"Enriching {total} tracks from Last.fm")

    for i, (track_id, title, artist_name) in enumerate(tracks):
        tags = await fetch_track_tags(network, artist_name or "", title)
        track_stats_data = await fetch_track_stats(network, artist_name or "", title)

        tags_added, stats_added = persist_track_enrichment(str(track_id), tags, track_stats_data)
        stats["tags_added"] += tags_added
        stats["stats_added"] += stats_added
        stats["tracks_processed"] += 1

        if progress_callback and (i + 1) % 20 == 0:
            progress_callback(i + 1, total, f"Enriched {i + 1}/{total} tracks")

        if (i + 1) % 100 == 0:
            logger.info(f"Enriching {i + 1}/{total} tracks (saved to DB)")

        await asyncio.sleep(delay_between_requests)

    if progress_callback:
        progress_callback(total, total, f"Last.fm track enrichment complete: {total} tracks processed")

    return stats
