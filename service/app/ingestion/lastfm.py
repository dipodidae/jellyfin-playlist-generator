import asyncio
import logging
from typing import Any

import pylast

from app.config import settings
from app.database_pg import get_connection, record_enrichment_attempts
from app.ingestion.album_tags import save_album_tags

logger = logging.getLogger(__name__)


# Last.fm matches artist/album/track names as literal strings. This library is
# tagged MusicBrainz/Picard-style, which uses typographic punctuation -- U+2019
# for apostrophes, U+2026 for ellipses, U+2010/2013/2014 for hyphens and
# dashes. Last.fm's own catalogue uses the ASCII forms, so an exact lookup on
# the tagged name returns nothing at all.
#
# Measured 2026-09-16, five for five:
#   "Script for a Jester’s Tear"            -> 0 tags
#   "Script for a Jester's Tear"            -> 10 tags
#   "The Four Instructive Tales …of Deco.." -> 0 tags
#   "The Four Instructive Tales ...of Deco.." -> 10 tags
#   "a‐ha"                                  -> 0 tags
#   "a-ha"                                   ->  9 tags
#
# So every lookup retries once with the punctuation folded to ASCII. The fold
# is punctuation-only on purpose: letters keep their diacritics, because
# Last.fm does hold "Motörhead" and "Sigur Rós" under their real names and
# stripping those would break lookups that currently work.
_PUNCTUATION_FOLD = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "ʼ": "'", "´": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
    "⁄": "/", "∕": "/",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    "​": "", "‌": "", "‍": "", "﻿": "",
    "…": "...",
})


def fold_punctuation(value: str) -> str:
    """Fold typographic punctuation to ASCII. Letters are left untouched."""
    return (value or "").translate(_PUNCTUATION_FOLD)


def _folded_variant(*names: str) -> tuple[str, ...] | None:
    """Return the ASCII-folded names, or None when folding changes nothing.

    None means "do not retry" -- there is no point spending a second Last.fm
    call on an identical query.
    """
    folded = tuple(fold_punctuation(n) for n in names)
    return folded if folded != tuple(names) else None


def get_lastfm_network() -> pylast.LastFMNetwork:
    if not settings.lastfm_api_key:
        raise ValueError("Last.fm API key must be configured")

    return pylast.LastFMNetwork(
        api_key=settings.lastfm_api_key,
        api_secret=settings.lastfm_api_secret,
    )


async def _fetch_artist_tags_once(
    network: pylast.LastFMNetwork, artist_name: str
) -> list[dict[str, Any]]:
    """One artist.getTopTags call, exactly as named."""
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


async def _fetch_album_tags_once(
    network: pylast.LastFMNetwork, artist_name: str, album_title: str
) -> list[dict[str, Any]]:
    """One album.getTopTags call, exactly as named."""
    try:
        album = network.get_album(artist_name, album_title)
        top_tags = await asyncio.to_thread(album.get_top_tags, limit=10)
        return [{"name": tag.item.name.lower(), "weight": int(tag.weight)} for tag in top_tags]
    except pylast.WSError as e:
        if "Album not found" in str(e):
            logger.debug(f"Album not found on Last.fm: {artist_name} - {album_title}")
        else:
            logger.warning(f"Last.fm error for album {artist_name} - {album_title}: {e}")
        return []
    except Exception as e:
        logger.warning(f"Error fetching tags for album {artist_name} - {album_title}: {e}")
        return []


async def _fetch_track_tags_once(
    network: pylast.LastFMNetwork, artist_name: str, track_title: str
) -> list[dict[str, Any]]:
    """One track.getTopTags call, exactly as named."""
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


async def _fetch_similar_artists_once(
    network: pylast.LastFMNetwork, artist_name: str
) -> list[dict[str, Any]]:
    """One artist.getSimilar call, exactly as named."""
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


async def _fetch_track_stats_once(
    network: pylast.LastFMNetwork, artist_name: str, track_title: str
) -> dict[str, int] | None:
    """One getPlaycount + getListenerCount pair, exactly as named."""
    try:
        track = network.get_track(artist_name, track_title)
        playcount = await asyncio.to_thread(track.get_playcount)
        listener_count = await asyncio.to_thread(track.get_listener_count)
        return {"playcount": playcount or 0, "listeners": listener_count or 0}
    except Exception as e:
        logger.debug(f"Error fetching stats for {artist_name} - {track_title}: {e}")
        return None


# --- public fetchers: exact name first, ASCII-folded name as a fallback ------
#
# Each retries once and only when folding actually changes the string, so the
# extra Last.fm call is spent only on names that could not have matched.


async def fetch_artist_tags(
    network: pylast.LastFMNetwork, artist_name: str
) -> list[dict[str, Any]]:
    """Fetch top tags for an artist from Last.fm."""
    tags = await _fetch_artist_tags_once(network, artist_name)
    if tags:
        return tags
    folded = _folded_variant(artist_name)
    if folded is None:
        return tags
    logger.debug("Retrying artist tags with folded name: %r", folded[0])
    return await _fetch_artist_tags_once(network, *folded)


async def fetch_album_tags(
    network: pylast.LastFMNetwork, artist_name: str, album_title: str
) -> list[dict[str, Any]]:
    """Fetch top tags for an album from Last.fm (album.getTopTags)."""
    tags = await _fetch_album_tags_once(network, artist_name, album_title)
    if tags:
        return tags
    folded = _folded_variant(artist_name, album_title)
    if folded is None:
        return tags
    logger.debug("Retrying album tags with folded name: %r - %r", *folded)
    return await _fetch_album_tags_once(network, *folded)


async def fetch_track_tags(
    network: pylast.LastFMNetwork, artist_name: str, track_title: str
) -> list[dict[str, Any]]:
    """Fetch top tags for a track from Last.fm."""
    tags = await _fetch_track_tags_once(network, artist_name, track_title)
    if tags:
        return tags
    folded = _folded_variant(artist_name, track_title)
    if folded is None:
        return tags
    return await _fetch_track_tags_once(network, *folded)


async def fetch_similar_artists(
    network: pylast.LastFMNetwork, artist_name: str
) -> list[dict[str, Any]]:
    """Fetch similar artists from Last.fm."""
    similar = await _fetch_similar_artists_once(network, artist_name)
    if similar:
        return similar
    folded = _folded_variant(artist_name)
    if folded is None:
        return similar
    return await _fetch_similar_artists_once(network, *folded)


async def fetch_track_stats(
    network: pylast.LastFMNetwork, artist_name: str, track_title: str
) -> dict[str, int] | None:
    """Fetch playcount and listener count for a track."""
    stats = await _fetch_track_stats_once(network, artist_name, track_title)
    # A found-but-unplayed track legitimately reports zeroes; only a miss
    # (None) is worth a second call.
    if stats is not None:
        return stats
    folded = _folded_variant(artist_name, track_title)
    if folded is None:
        return stats
    return await _fetch_track_stats_once(network, *folded)


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

    # Two fixes over the pre-2026-09-16 `ORDER BY RANDOM()` on the same WHERE.
    #
    # 1. The candidate pool was effectively the whole library. Last.fm holds
    #    track-level tags for almost nothing here -- 582 of 162,705 tracks,
    #    0.36% -- so `tlt.track_id IS NULL` is true for essentially every row
    #    and the `OR` swallowed the selective half. Picking 300 at random from
    #    153,060 when only 6,634 actually lacked STATS meant ~96% of every
    #    batch was re-fetching data already held: measured ~13 newly covered
    #    tracks per 300-call run.
    # 2. Random order cannot guarantee coverage. Ordering by attempt age does:
    #    every track is tried once before any is tried twice.
    #
    # Missing stats sorts first because that is the half with a ~98% hit rate;
    # the tag half is still swept, just behind it.
    query = """
        SELECT t.id, t.title, a.name as artist_name
        FROM tracks t
        LEFT JOIN track_artists ta ON ta.track_id = t.id AND ta.role = 'primary'
        LEFT JOIN artists a ON ta.artist_id = a.id
        LEFT JOIN track_lastfm_tags tlt ON t.id = tlt.track_id
        LEFT JOIN lastfm_stats ls ON t.id = ls.track_id
        LEFT JOIN enrichment_attempts ea
               ON ea.scope = 'lastfm_track' AND ea.entity_id = t.id
        WHERE tlt.track_id IS NULL OR ls.track_id IS NULL
        ORDER BY (ls.track_id IS NULL) DESC,
                 ea.attempted_at ASC NULLS FIRST,
                 t.id
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

    attempted: list[str] = []
    found: set[str] = set()

    for i, (track_id, title, artist_name) in enumerate(tracks):
        attempted.append(str(track_id))
        tags = await fetch_track_tags(network, artist_name or "", title)
        track_stats_data = await fetch_track_stats(network, artist_name or "", title)

        tags_added, stats_added = persist_track_enrichment(str(track_id), tags, track_stats_data)
        if tags_added or stats_added:
            found.add(str(track_id))
        stats["tags_added"] += tags_added
        stats["stats_added"] += stats_added
        stats["tracks_processed"] += 1

        if progress_callback and (i + 1) % 20 == 0:
            progress_callback(i + 1, total, f"Enriched {i + 1}/{total} tracks")

        if (i + 1) % 100 == 0:
            logger.info(f"Enriching {i + 1}/{total} tracks (saved to DB)")

        await asyncio.sleep(delay_between_requests)

    # Stamp every track we looked at, so the sweep advances even when Last.fm
    # has nothing for it.
    if attempted:
        with get_connection() as conn:
            with conn.cursor() as cur:
                record_enrichment_attempts(cur, "lastfm_track", attempted, found)

    if progress_callback:
        progress_callback(total, total, f"Last.fm track enrichment complete: {total} tracks processed")

    return stats


async def enrich_albums_from_lastfm_tags(
    delay_between_requests: float = 0.2,
    max_albums: int | None = None,
    force: bool = False,
    progress_callback: Any = None,
) -> dict[str, int]:
    """Fetch album.getTopTags for albums and store them in album_tags (P2).

    The album's artist is derived from its tracks' primary artist. Albums
    already having Last.fm album tags are skipped unless ``force``.
    """
    network = get_lastfm_network()

    # Least-recently-attempted first, never-attempted before that. Ordering by
    # al.id instead (as this did until 2026-09-16) wedges permanently the
    # moment the first `max_albums` candidates are all albums Last.fm has no
    # tags for: nothing is written, the candidate set is unchanged, and the
    # next run re-selects the identical batch. Measured: 300 albums/hour,
    # 0 tagged, for weeks, with 6,032 albums never attempted once. See
    # migration 019.
    query = """
        SELECT al.id, al.title,
               (SELECT ar.name
                  FROM track_albums tal
                  JOIN track_artists ta
                    ON ta.track_id = tal.track_id AND ta.role = 'primary'
                  JOIN artists ar ON ar.id = ta.artist_id
                  WHERE tal.album_id = al.id
                  LIMIT 1) AS artist_name
        FROM albums al
        LEFT JOIN enrichment_attempts ea
               ON ea.scope = 'lastfm_album_tags' AND ea.entity_id = al.id
    """
    if not force:
        query += (
            " WHERE NOT EXISTS (SELECT 1 FROM album_tags at "
            "WHERE at.album_id = al.id AND at.source = 'lastfm')"
        )
    query += " ORDER BY ea.attempted_at ASC NULLS FIRST, al.id"
    if max_albums:
        query += f" LIMIT {max_albums}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            albums = cur.fetchall()

    stats: dict[str, int] = {"albums_processed": 0, "albums_tagged": 0, "tags_added": 0}
    total = len(albums)
    logger.info(f"Enriching {total} albums with Last.fm tags")

    attempted: list[str] = []
    found: set[str] = set()

    for i, (album_id, title, artist_name) in enumerate(albums):
        attempted.append(str(album_id))
        if artist_name and title:
            tags = await fetch_album_tags(network, artist_name, title)
            if tags:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        added = save_album_tags(cur, str(album_id), "lastfm", tags, kind="tag")
                stats["tags_added"] += added
                stats["albums_tagged"] += 1
                found.add(str(album_id))
        stats["albums_processed"] += 1

        if progress_callback and (i + 1) % 20 == 0:
            progress_callback(i + 1, total, f"Enriched {i + 1}/{total} albums")

        await asyncio.sleep(delay_between_requests)

    # Stamp every album we looked at, tagged or not. Without this the next run
    # picks the same batch again.
    if attempted:
        with get_connection() as conn:
            with conn.cursor() as cur:
                record_enrichment_attempts(cur, "lastfm_album_tags", attempted, found)

    if progress_callback:
        progress_callback(total, total, f"Last.fm album-tag enrichment complete: {total} albums")

    return stats
