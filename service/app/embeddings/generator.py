import asyncio
import logging
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

from app.database_pg import get_connection

logger = logging.getLogger(__name__)

# Global model instance (loaded once)
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """Get or load the sentence transformer model."""
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model...")
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        logger.info("Model loaded successfully")
    return _model


def build_track_text(track: dict[str, Any]) -> str:
    """Build a text representation of a track for embedding.

    Combines multiple metadata fields into a rich text description.
    """
    parts = []

    # Core metadata
    if track.get("title"):
        parts.append(track["title"])
    if track.get("artist_name"):
        parts.append(f"by {track['artist_name']}")
    if track.get("album_name"):
        parts.append(f"from album {track['album_name']}")
    if track.get("year"):
        parts.append(f"({track['year']})")

    # Genre information
    if track.get("genres"):
        parts.append(f"genres: {', '.join(track['genres'])}")

    # Last.fm tags (weighted by importance)
    if track.get("tags"):
        # Sort by weight and take top tags
        sorted_tags = sorted(track["tags"], key=lambda t: t.get("weight", 0), reverse=True)
        top_tags = [t["name"] for t in sorted_tags[:10]]
        if top_tags:
            parts.append(f"tags: {', '.join(top_tags)}")

    # Artist tags (if no track-specific tags)
    if not track.get("tags") and track.get("artist_tags"):
        sorted_tags = sorted(track["artist_tags"], key=lambda t: t.get("weight", 0), reverse=True)
        top_tags = [t["name"] for t in sorted_tags[:5]]
        if top_tags:
            parts.append(f"artist style: {', '.join(top_tags)}")

    return " ".join(parts)


def generate_embedding(text: str) -> list[float]:
    """Generate embedding for a text string."""
    model = get_model()
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()


def generate_embeddings_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Generate embeddings for multiple texts efficiently."""
    model = get_model()
    embeddings = model.encode(texts, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=True)
    return embeddings.tolist()


def get_track_with_metadata(cur, track_id: str) -> dict[str, Any] | None:
    """Fetch a track with all its metadata for embedding (PostgreSQL)."""
    cur.execute("""
        SELECT
            t.id, t.title, t.year,
            a.name as artist_name,
            al.title as album_name
        FROM tracks t
        LEFT JOIN track_artists ta ON ta.track_id = t.id AND ta.role = 'primary'
        LEFT JOIN artists a ON ta.artist_id = a.id
        LEFT JOIN track_albums tal ON tal.track_id = t.id
        LEFT JOIN albums al ON tal.album_id = al.id
        WHERE t.id = %s
        LIMIT 1
    """, (track_id,))
    row = cur.fetchone()
    if not row:
        return None

    result: dict[str, Any] = {
        "id": str(row[0]),
        "title": row[1],
        "year": row[2],
        "artist_name": row[3],
        "album_name": row[4],
    }

    cur.execute("""
        SELECT g.name FROM genres g
        JOIN track_genres tg ON g.id = tg.genre_id
        WHERE tg.track_id = %s
    """, (track_id,))
    result["genres"] = [r[0] for r in cur.fetchall()]

    cur.execute("""
        SELECT lt.name, tlt.weight FROM lastfm_tags lt
        JOIN track_lastfm_tags tlt ON lt.id = tlt.tag_id
        WHERE tlt.track_id = %s
        ORDER BY tlt.weight DESC
        LIMIT 15
    """, (track_id,))
    tags = cur.fetchall()
    result["tags"] = [{"name": r[0], "weight": r[1]} for r in tags]

    if not result["tags"]:
        cur.execute("""
            SELECT lt.name, MAX(alt.weight) as weight
            FROM lastfm_tags lt
            JOIN artist_lastfm_tags alt ON lt.id = alt.tag_id
            JOIN track_artists ta ON ta.artist_id = alt.artist_id
            WHERE ta.track_id = %s
            GROUP BY lt.name
            ORDER BY MAX(alt.weight) DESC, lt.name
            LIMIT 10
        """, (track_id,))
        result["artist_tags"] = [{"name": r[0], "weight": r[1]} for r in cur.fetchall()]

    return result


def save_track_embedding(cur, track_id: str, embedding: list[float], text_used: str) -> None:
    """Save a track embedding to the database (PostgreSQL + pgvector)."""
    cur.execute("""
        INSERT INTO track_embeddings (track_id, embedding, embedding_text, status, computed_at)
        VALUES (%s, %s::vector, %s, 'ready', now())
        ON CONFLICT (track_id) DO UPDATE SET
            embedding = EXCLUDED.embedding,
            embedding_text = EXCLUDED.embedding_text,
            status = 'ready',
            computed_at = now()
    """, (track_id, embedding, text_used))


async def generate_track_embeddings(
    batch_size: int = 100,
    max_tracks: int | None = None,
    progress_callback=None,
) -> dict[str, int]:
    """Generate embeddings for tracks that don't have them yet (PostgreSQL)."""
    stats = {"processed": 0, "embedded": 0, "errors": 0}

    with get_connection() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT t.id FROM tracks t
                LEFT JOIN track_embeddings te ON t.id = te.track_id
                WHERE te.track_id IS NULL OR te.status != 'ready'
            """
            if max_tracks:
                query += f" LIMIT {max_tracks}"
            cur.execute(query)
            track_ids = [str(row[0]) for row in cur.fetchall()]

    if not track_ids:
        logger.info("All tracks have embeddings")
        return stats

    logger.info(f"Generating embeddings for {len(track_ids)} tracks")

    for i in range(0, len(track_ids), batch_size):
        batch_ids = track_ids[i:i + batch_size]
        tracks_data = []
        texts = []

        with get_connection() as conn:
            with conn.cursor() as cur:
                for track_id in batch_ids:
                    track = get_track_with_metadata(cur, track_id)
                    if track:
                        text = build_track_text(track)
                        tracks_data.append(track)
                        texts.append(text)

        if not texts:
            stats["processed"] += len(batch_ids)
            continue

        try:
            embeddings = await asyncio.to_thread(generate_embeddings_batch, texts, batch_size)

            with get_connection() as conn:
                with conn.cursor() as cur:
                    for track, embedding, text in zip(tracks_data, embeddings, texts):
                        save_track_embedding(cur, track["id"], embedding, text)
                        stats["embedded"] += 1

            stats["processed"] += len(batch_ids)
            done = min(i + batch_size, len(track_ids))
            if done % 500 == 0 or done >= len(track_ids):
                logger.info(f"Embedded {done}/{len(track_ids)} tracks")
            if progress_callback:
                progress_callback(done, len(track_ids), f"Embedded {done}/{len(track_ids)} tracks")

        except Exception as e:
            logger.error(f"Error generating embeddings for batch starting at {i}: {e}")
            stats["errors"] += len(batch_ids)

    return stats


def search_similar_tracks(query_embedding: list[float], limit: int = 50) -> list[dict[str, Any]]:
    """Find tracks similar to a query embedding using pgvector cosine similarity."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    t.id, t.title,
                    a.name as artist_name,
                    al.title as album_name,
                    t.year, t.duration_ms,
                    1 - (te.embedding <=> %s::vector) as similarity
                FROM track_embeddings te
                JOIN tracks t ON te.track_id = t.id
                LEFT JOIN track_artists ta ON ta.track_id = t.id AND ta.role = 'primary'
                LEFT JOIN artists a ON ta.artist_id = a.id
                LEFT JOIN track_albums tal ON tal.track_id = t.id
                LEFT JOIN albums al ON tal.album_id = al.id
                WHERE te.embedding IS NOT NULL
                ORDER BY te.embedding <=> %s::vector
                LIMIT %s
            """, (query_embedding, query_embedding, limit))
            rows = cur.fetchall()

    return [
        {
            "id": str(r[0]),
            "title": r[1],
            "artist_name": r[2],
            "album_name": r[3],
            "year": r[4],
            "duration_ms": r[5],
            "similarity": float(r[6]) if r[6] is not None else 0.0,
        }
        for r in rows
    ]


def search_tracks_by_text(query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Search for tracks similar to a text query."""
    embedding = generate_embedding(query)
    return search_similar_tracks(embedding, limit)
