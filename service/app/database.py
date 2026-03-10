import duckdb
from pathlib import Path

from app.config import settings


def get_connection() -> duckdb.DuckDBPyConnection:
    """Get a DuckDB connection, creating the database if needed."""
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def init_database() -> None:
    """Initialize the database schema."""
    conn = get_connection()
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id VARCHAR PRIMARY KEY,
            title VARCHAR NOT NULL,
            artist_id VARCHAR,
            artist_name VARCHAR,
            album_id VARCHAR,
            album_name VARCHAR,
            year INTEGER,
            duration_ms INTEGER,
            track_number INTEGER,
            disc_number INTEGER,
            path VARCHAR,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now()
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artists (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            sort_name VARCHAR,
            musicbrainz_id VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS albums (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            artist_id VARCHAR,
            artist_name VARCHAR,
            year INTEGER,
            musicbrainz_id VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS genres (
            id INTEGER PRIMARY KEY,
            name VARCHAR UNIQUE NOT NULL,
            normalized_name VARCHAR
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS track_genres (
            track_id VARCHAR,
            genre_id INTEGER,
            PRIMARY KEY (track_id, genre_id)
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lastfm_tags (
            id INTEGER PRIMARY KEY,
            name VARCHAR UNIQUE NOT NULL,
            normalized_name VARCHAR
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS track_lastfm_tags (
            track_id VARCHAR,
            tag_id INTEGER,
            weight INTEGER DEFAULT 100,
            PRIMARY KEY (track_id, tag_id)
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artist_lastfm_tags (
            artist_id VARCHAR,
            tag_id INTEGER,
            weight INTEGER DEFAULT 100,
            PRIMARY KEY (artist_id, tag_id)
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lastfm_stats (
            track_id VARCHAR PRIMARY KEY,
            playcount INTEGER DEFAULT 0,
            listeners INTEGER DEFAULT 0,
            artist_playcount INTEGER DEFAULT 0,
            fetched_at TIMESTAMP
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS local_stats (
            track_id VARCHAR PRIMARY KEY,
            play_count INTEGER DEFAULT 0,
            last_played TIMESTAMP,
            favorite BOOLEAN DEFAULT FALSE
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS track_features (
            track_id VARCHAR PRIMARY KEY,
            energy FLOAT DEFAULT 0.5,
            darkness FLOAT DEFAULT 0.5,
            atmosphere FLOAT DEFAULT 0.5,
            aggression FLOAT DEFAULT 0.5,
            density FLOAT DEFAULT 0.5,
            tempo FLOAT DEFAULT 0.5,
            confidence FLOAT DEFAULT 0.0,
            computed_at TIMESTAMP
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS track_embeddings (
            track_id VARCHAR PRIMARY KEY,
            embedding FLOAT[384],
            embedding_text VARCHAR,
            computed_at TIMESTAMP
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artist_similarity (
            artist_id VARCHAR,
            similar_artist_id VARCHAR,
            similarity FLOAT,
            fetched_at TIMESTAMP,
            PRIMARY KEY (artist_id, similar_artist_id)
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS genre_similarity (
            genre_a VARCHAR,
            genre_b VARCHAR,
            similarity FLOAT,
            PRIMARY KEY (genre_a, genre_b)
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS playlists (
            id VARCHAR PRIMARY KEY,
            prompt TEXT NOT NULL,
            jellyfin_playlist_id VARCHAR,
            track_count INTEGER,
            trajectory_json TEXT,
            intent_json TEXT,
            arc_type VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS playlist_tracks (
            playlist_id VARCHAR,
            track_id VARCHAR,
            position INTEGER,
            score FLOAT,
            phase VARCHAR,
            PRIMARY KEY (playlist_id, position)
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS playlist_fingerprints (
            playlist_id VARCHAR PRIMARY KEY,
            prompt_embedding FLOAT[384],
            combined_embedding FLOAT[384],
            intent_features_json TEXT,
            arc_type VARCHAR,
            waypoints_json TEXT,
            track_features_json TEXT,
            user_rating INTEGER,
            created_at TIMESTAMP DEFAULT now()
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompt_cache (
            prompt_hash VARCHAR PRIMARY KEY,
            prompt TEXT NOT NULL,
            intent_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT now(),
            hit_count INTEGER DEFAULT 0
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_metadata (
            key VARCHAR PRIMARY KEY,
            value VARCHAR,
            updated_at TIMESTAMP DEFAULT now()
        )
    """)
    
    conn.close()


def get_stats() -> dict:
    """Get database statistics."""
    conn = get_connection()
    
    stats = {}
    for table in ["tracks", "artists", "albums", "genres", "lastfm_tags", "playlists"]:
        result = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        stats[table] = result[0] if result else 0
    
    # Enrichment stats
    stats["artists_with_tags"] = conn.execute(
        "SELECT COUNT(DISTINCT artist_id) FROM artist_lastfm_tags"
    ).fetchone()[0]
    stats["artist_similarities"] = conn.execute(
        "SELECT COUNT(*) FROM artist_similarity"
    ).fetchone()[0]
    stats["tracks_with_tags"] = conn.execute(
        "SELECT COUNT(DISTINCT track_id) FROM track_lastfm_tags"
    ).fetchone()[0]
    stats["tracks_with_embeddings"] = conn.execute(
        "SELECT COUNT(*) FROM track_embeddings"
    ).fetchone()[0]
    
    conn.close()
    return stats
