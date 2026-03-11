"""PostgreSQL + pgvector database module."""

import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None


def get_pool() -> ThreadedConnectionPool:
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=settings.database_url,
        )
    return _pool


@contextmanager
def get_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """Get a connection from the pool."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(dict_cursor: bool = False) -> Generator[psycopg2.extensions.cursor, None, None]:
    """Get a cursor with automatic connection management."""
    with get_connection() as conn:
        cursor_factory = RealDictCursor if dict_cursor else None
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            yield cur


def init_database() -> None:
    """Initialize the database schema with pgvector."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Enable pgvector extension
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")  # For fuzzy text search

            # Tracks - fuzzy identity via fingerprint
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    fingerprint VARCHAR UNIQUE NOT NULL,
                    title VARCHAR NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    year INTEGER,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tracks_duration ON tracks(duration_ms)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tracks_fingerprint ON tracks(fingerprint)")

            # Track files - separate from track identity
            cur.execute("""
                CREATE TABLE IF NOT EXISTS track_files (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    track_id UUID REFERENCES tracks(id) ON DELETE CASCADE,
                    path VARCHAR UNIQUE NOT NULL,
                    file_hash VARCHAR,
                    size BIGINT NOT NULL,
                    mtime TIMESTAMPTZ NOT NULL,
                    inode BIGINT,
                    format VARCHAR NOT NULL,
                    last_scanned TIMESTAMPTZ DEFAULT now(),
                    missing_since TIMESTAMPTZ
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_track_files_track ON track_files(track_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_track_files_missing ON track_files(missing_since) WHERE missing_since IS NOT NULL")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_track_files_hash ON track_files(file_hash)")

            # Artists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS artists (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR UNIQUE NOT NULL,
                    sort_name VARCHAR,
                    musicbrainz_id VARCHAR
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_artists_name_trgm ON artists USING gin(name gin_trgm_ops)")

            # Albums
            cur.execute("""
                CREATE TABLE IF NOT EXISTS albums (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    title VARCHAR NOT NULL,
                    year INTEGER,
                    musicbrainz_id VARCHAR,
                    UNIQUE(title, year)
                )
            """)

            # Track artists (many-to-many)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS track_artists (
                    track_id UUID REFERENCES tracks(id) ON DELETE CASCADE,
                    artist_id UUID REFERENCES artists(id) ON DELETE CASCADE,
                    role VARCHAR DEFAULT 'primary',
                    position INTEGER DEFAULT 0,
                    PRIMARY KEY (track_id, artist_id, role)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_track_artists_artist ON track_artists(artist_id)")

            # Album artists (many-to-many)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS album_artists (
                    album_id UUID REFERENCES albums(id) ON DELETE CASCADE,
                    artist_id UUID REFERENCES artists(id) ON DELETE CASCADE,
                    position INTEGER DEFAULT 0,
                    PRIMARY KEY (album_id, artist_id)
                )
            """)

            # Track to album
            cur.execute("""
                CREATE TABLE IF NOT EXISTS track_albums (
                    track_id UUID REFERENCES tracks(id) ON DELETE CASCADE,
                    album_id UUID REFERENCES albums(id) ON DELETE CASCADE,
                    disc_number INTEGER DEFAULT 1,
                    track_number INTEGER,
                    PRIMARY KEY (track_id, album_id)
                )
            """)

            # Genres
            cur.execute("""
                CREATE TABLE IF NOT EXISTS genres (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR UNIQUE NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS track_genres (
                    track_id UUID REFERENCES tracks(id) ON DELETE CASCADE,
                    genre_id UUID REFERENCES genres(id) ON DELETE CASCADE,
                    PRIMARY KEY (track_id, genre_id)
                )
            """)

            # Last.fm tags
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lastfm_tags (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR UNIQUE NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS artist_lastfm_tags (
                    artist_id UUID REFERENCES artists(id) ON DELETE CASCADE,
                    tag_id INTEGER REFERENCES lastfm_tags(id) ON DELETE CASCADE,
                    weight INTEGER DEFAULT 100,
                    PRIMARY KEY (artist_id, tag_id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS track_lastfm_tags (
                    track_id UUID REFERENCES tracks(id) ON DELETE CASCADE,
                    tag_id INTEGER REFERENCES lastfm_tags(id) ON DELETE CASCADE,
                    weight INTEGER DEFAULT 100,
                    PRIMARY KEY (track_id, tag_id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS artist_similarity (
                    artist_id UUID REFERENCES artists(id) ON DELETE CASCADE,
                    similar_artist_id UUID REFERENCES artists(id) ON DELETE CASCADE,
                    similarity FLOAT,
                    PRIMARY KEY (artist_id, similar_artist_id)
                )
            """)

            # Embeddings with pgvector
            cur.execute("""
                CREATE TABLE IF NOT EXISTS track_embeddings (
                    track_id UUID PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                    embedding vector(384),
                    embedding_text TEXT,
                    embedding_version INTEGER DEFAULT 1,
                    metadata_hash VARCHAR,
                    status VARCHAR(20) DEFAULT 'ready',
                    computed_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            # IVFFlat index: created only when enough embeddings exist (≥1000)
            cur.execute("SELECT COUNT(*) FROM track_embeddings")
            embedding_count = (cur.fetchone() or [0])[0]
            if embedding_count >= 1000:
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_embeddings_vector
                    ON track_embeddings USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                """)
                logger.info(f"IVFFlat index ensured ({embedding_count} embeddings)")

            # Semantic track profiles (4D: energy, darkness, tempo, texture)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS track_profiles (
                    track_id UUID PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                    energy FLOAT,
                    darkness FLOAT,
                    tempo FLOAT,
                    texture FLOAT,
                    computed_at TIMESTAMPTZ DEFAULT now()
                )
            """)

            # Path mappings for M3U export
            cur.execute("""
                CREATE TABLE IF NOT EXISTS path_mappings (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR UNIQUE NOT NULL,
                    source_prefix VARCHAR NOT NULL,
                    target_prefix VARCHAR NOT NULL,
                    priority INTEGER DEFAULT 0
                )
            """)

            # Generated playlists (relational)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS generated_playlists (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    prompt TEXT NOT NULL,
                    seed INTEGER,
                    track_count INTEGER NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS playlist_tracks (
                    playlist_id UUID REFERENCES generated_playlists(id) ON DELETE CASCADE,
                    track_id UUID REFERENCES tracks(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (playlist_id, track_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_playlist_tracks_pos ON playlist_tracks(playlist_id, position)")

            # Audio features (optional, for enhanced scoring)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS track_audio_features (
                    track_id UUID PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                    bpm REAL,
                    loudness_rms REAL,
                    loudness_lufs REAL,
                    spectral_centroid REAL,
                    spectral_flatness REAL,
                    dynamic_range REAL,
                    key_estimate VARCHAR(10),
                    bpm_norm REAL,
                    loudness_norm REAL,
                    brightness_norm REAL,
                    flatness_norm REAL,
                    analyzed_at TIMESTAMPTZ DEFAULT now()
                )
            """)

            # Playlist generation log (observability)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS playlist_generation_log (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    prompt TEXT,
                    arc_type VARCHAR(20),
                    playlist_length INTEGER,
                    generation_time_ms INTEGER,
                    trajectory_deviation REAL,
                    pool_entropy REAL,
                    avg_transition_cost REAL,
                    beam_dead_ends INTEGER DEFAULT 0,
                    constraint_rejections INTEGER DEFAULT 0,
                    bridge_tracks_used INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
            """)

            # Scene clusters (created here so stats queries always work)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scene_clusters (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(100),
                    centroid vector(384),
                    size INTEGER
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS artist_clusters (
                    artist_id UUID REFERENCES artists(id) ON DELETE CASCADE,
                    cluster_id INTEGER REFERENCES scene_clusters(id),
                    weight FLOAT,
                    PRIMARY KEY (artist_id, cluster_id)
                )
            """)

            # Track usage for playlist memory with time decay
            cur.execute("""
                CREATE TABLE IF NOT EXISTS track_usage (
                    track_id UUID PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                    last_used_at TIMESTAMPTZ,
                    usage_count INTEGER DEFAULT 0
                )
            """)

            # Directory scan checkpoints
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scan_directories (
                    path VARCHAR PRIMARY KEY,
                    file_count INTEGER,
                    last_scanned TIMESTAMPTZ,
                    dir_mtime TIMESTAMPTZ
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS scan_jobs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    status VARCHAR(20) NOT NULL,
                    scan_type VARCHAR(20) NOT NULL DEFAULT 'incremental',
                    stage VARCHAR(50) NOT NULL DEFAULT 'idle',
                    started_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ DEFAULT now(),
                    completed_at TIMESTAMPTZ,
                    current INTEGER DEFAULT 0,
                    total INTEGER DEFAULT 0,
                    files_found INTEGER DEFAULT 0,
                    files_scanned INTEGER DEFAULT 0,
                    files_skipped INTEGER DEFAULT 0,
                    tracks_added INTEGER DEFAULT 0,
                    tracks_updated INTEGER DEFAULT 0,
                    files_missing INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    current_message TEXT,
                    error_summary TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scan_jobs_status_started ON scan_jobs(status, started_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scan_jobs_completed ON scan_jobs(completed_at DESC)")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS scan_job_events (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    job_id UUID NOT NULL REFERENCES scan_jobs(id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    stage VARCHAR(50) NOT NULL,
                    event_type VARCHAR(20) NOT NULL DEFAULT 'progress',
                    message TEXT,
                    current INTEGER DEFAULT 0,
                    total INTEGER DEFAULT 0,
                    payload JSONB
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scan_job_events_job_created ON scan_job_events(job_id, created_at DESC)")

            # Sync metadata (for migration tracking)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sync_metadata (
                    key VARCHAR PRIMARY KEY,
                    value VARCHAR,
                    updated_at TIMESTAMPTZ DEFAULT now()
                )
            """)

            logger.info("Database schema initialized")


def get_stats() -> dict:
    """Get database statistics."""
    with get_cursor() as cur:
        stats = {}

        # Core counts
        for table in ["tracks", "artists", "albums", "genres", "lastfm_tags", "generated_playlists"]:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            result = cur.fetchone()
            key = "playlists" if table == "generated_playlists" else table
            stats[key] = result[0] if result else 0

        # Track files
        cur.execute("SELECT COUNT(*) FROM track_files WHERE missing_since IS NULL")
        stats["track_files"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM track_files WHERE missing_since IS NOT NULL")
        stats["missing_files"] = cur.fetchone()[0]

        # Enrichment stats
        cur.execute("SELECT COUNT(DISTINCT artist_id) FROM artist_lastfm_tags")
        stats["artists_with_tags"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM artist_similarity")
        stats["artist_similarities"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT track_id) FROM track_lastfm_tags")
        stats["tracks_with_tags"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM track_embeddings")
        stats["tracks_with_embeddings"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM track_profiles")
        stats["tracks_with_profiles"] = cur.fetchone()[0]

        # Cluster counts (use SAVEPOINT so a missing table can't abort the txn)
        cur.execute("SAVEPOINT sp_clusters")
        try:
            cur.execute("SELECT COUNT(*) FROM scene_clusters")
            stats["scene_clusters"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT artist_id) FROM artist_clusters")
            stats["artists_clustered"] = cur.fetchone()[0]
            cur.execute("RELEASE SAVEPOINT sp_clusters")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT sp_clusters")
            stats["scene_clusters"] = 0
            stats["artists_clustered"] = 0

        # IVFFlat index status
        cur.execute("""
            SELECT COUNT(*) FROM pg_indexes
            WHERE tablename = 'track_embeddings' AND indexname = 'idx_embeddings_vector'
        """)
        stats["vector_index_built"] = cur.fetchone()[0] > 0

        return stats


def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
