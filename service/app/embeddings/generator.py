import logging
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

from app.database import get_connection

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


def get_track_with_metadata(conn, track_id: str) -> dict[str, Any] | None:
    """Fetch a track with all its metadata for embedding."""
    track = conn.execute("""
        SELECT t.id, t.title, t.artist_name, t.album_name, t.year
        FROM tracks t
        WHERE t.id = ?
    """, [track_id]).fetchone()
    
    if not track:
        return None
    
    result = {
        "id": track[0],
        "title": track[1],
        "artist_name": track[2],
        "album_name": track[3],
        "year": track[4],
    }
    
    # Get genres
    genres = conn.execute("""
        SELECT g.name FROM genres g
        JOIN track_genres tg ON g.id = tg.genre_id
        WHERE tg.track_id = ?
    """, [track_id]).fetchall()
    result["genres"] = [g[0] for g in genres]
    
    # Get track tags
    tags = conn.execute("""
        SELECT lt.name, tlt.weight FROM lastfm_tags lt
        JOIN track_lastfm_tags tlt ON lt.id = tlt.tag_id
        WHERE tlt.track_id = ?
    """, [track_id]).fetchall()
    result["tags"] = [{"name": t[0], "weight": t[1]} for t in tags]
    
    # Get artist tags if no track tags
    if not result["tags"]:
        artist_tags = conn.execute("""
            SELECT lt.name, alt.weight FROM lastfm_tags lt
            JOIN artist_lastfm_tags alt ON lt.id = alt.tag_id
            JOIN tracks t ON t.artist_id = alt.artist_id
            WHERE t.id = ?
        """, [track_id]).fetchall()
        result["artist_tags"] = [{"name": t[0], "weight": t[1]} for t in artist_tags]
    
    return result


def save_track_embedding(conn, track_id: str, embedding: list[float], text_used: str) -> None:
    """Save a track embedding to the database."""
    # Convert to numpy array for storage
    embedding_array = np.array(embedding, dtype=np.float32)
    
    conn.execute("""
        INSERT INTO track_embeddings (track_id, embedding, embedding_text, computed_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (track_id) DO UPDATE SET
            embedding = excluded.embedding,
            embedding_text = excluded.embedding_text,
            computed_at = excluded.computed_at
    """, [track_id, embedding_array.tolist(), text_used])


async def generate_track_embeddings(batch_size: int = 100, max_tracks: int | None = None) -> dict[str, int]:
    """Generate embeddings for tracks that don't have them yet."""
    conn = get_connection()
    
    # Get tracks without embeddings
    query = """
        SELECT t.id FROM tracks t
        LEFT JOIN track_embeddings te ON t.id = te.track_id
        WHERE te.track_id IS NULL
    """
    if max_tracks:
        query += f" LIMIT {max_tracks}"
    
    track_ids = [row[0] for row in conn.execute(query).fetchall()]
    
    stats = {"processed": 0, "embedded": 0, "errors": 0}
    logger.info(f"Generating embeddings for {len(track_ids)} tracks")
    
    # Process in batches
    for i in range(0, len(track_ids), batch_size):
        batch_ids = track_ids[i:i + batch_size]
        
        # Fetch metadata for batch
        tracks_data = []
        texts = []
        for track_id in batch_ids:
            track = get_track_with_metadata(conn, track_id)
            if track:
                text = build_track_text(track)
                tracks_data.append(track)
                texts.append(text)
        
        if not texts:
            continue
        
        try:
            # Generate embeddings for batch
            embeddings = generate_embeddings_batch(texts, batch_size=batch_size)
            
            # Save embeddings
            for track, embedding, text in zip(tracks_data, embeddings, texts):
                save_track_embedding(conn, track["id"], embedding, text)
                stats["embedded"] += 1
            
            # Commit after each batch so progress is saved even if interrupted
            conn.commit()
            stats["processed"] += len(batch_ids)
            
            if (i + batch_size) % 500 == 0 or i + batch_size >= len(track_ids):
                logger.info(f"Embedded {min(i + batch_size, len(track_ids))}/{len(track_ids)} tracks (saved to DB)")
                
        except Exception as e:
            logger.error(f"Error generating embeddings for batch: {e}")
            stats["errors"] += len(batch_ids)
            # Still commit what we have so far
            conn.commit()
    
    conn.close()
    return stats


def search_similar_tracks(query_embedding: list[float], limit: int = 50) -> list[dict[str, Any]]:
    """Find tracks similar to a query embedding using cosine similarity."""
    conn = get_connection()
    
    # DuckDB supports array operations for similarity
    query_array = np.array(query_embedding, dtype=np.float32)
    
    # Use cosine similarity: dot(a, b) / (norm(a) * norm(b))
    results = conn.execute("""
        SELECT 
            t.id, t.title, t.artist_name, t.album_name, t.year, t.duration_ms,
            te.embedding,
            list_cosine_similarity(te.embedding, ?::FLOAT[384]) as similarity
        FROM track_embeddings te
        JOIN tracks t ON te.track_id = t.id
        ORDER BY similarity DESC
        LIMIT ?
    """, [query_array.tolist(), limit]).fetchall()
    
    conn.close()
    
    return [
        {
            "id": r[0],
            "title": r[1],
            "artist_name": r[2],
            "album_name": r[3],
            "year": r[4],
            "duration_ms": r[5],
            "similarity": r[7],
        }
        for r in results
    ]


def search_tracks_by_text(query: str, limit: int = 50) -> list[dict[str, Any]]:
    """Search for tracks similar to a text query."""
    embedding = generate_embedding(query)
    return search_similar_tracks(embedding, limit)
