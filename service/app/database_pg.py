"""PostgreSQL + pgvector database module."""

import logging
import time
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

            cur.execute("""
                CREATE TABLE IF NOT EXISTS lastfm_stats (
                    track_id UUID PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                    playcount INTEGER DEFAULT 0,
                    listeners INTEGER DEFAULT 0,
                    fetched_at TIMESTAMPTZ DEFAULT now()
                )
            """)

            # Album legitimacy (Metal Archives data)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS album_legitimacy (
                    album_id UUID PRIMARY KEY REFERENCES albums(id) ON DELETE CASCADE,
                    ma_url VARCHAR,
                    ma_rating FLOAT,
                    ma_review_count INTEGER DEFAULT 0,
                    match_confidence FLOAT DEFAULT 0.0,
                    scraped_at TIMESTAMPTZ DEFAULT now()
                )
            """)

            # Track banger flags (computed from Last.fm + other signals)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS track_banger_flags (
                    track_id UUID PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                    banger_score FLOAT DEFAULT 0.0,
                    confidence FLOAT DEFAULT 0.0,
                    sources JSONB DEFAULT '[]',
                    computed_at TIMESTAMPTZ DEFAULT now()
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

            # MusicBrainz lookup cache
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mb_release_groups (
                    mbid         VARCHAR(36) PRIMARY KEY,
                    title        VARCHAR NOT NULL,
                    artist_credit VARCHAR,
                    primary_type  VARCHAR(20),
                    first_release_year INTEGER,
                    fetched_at   TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mb_lookup_cache (
                    entity_type  VARCHAR(10) NOT NULL,
                    local_id     UUID NOT NULL,
                    mbid         VARCHAR(36),
                    match_score  FLOAT,
                    lookup_at    TIMESTAMPTZ DEFAULT now(),
                    PRIMARY KEY (entity_type, local_id)
                )
            """)

            # RYM album-level data
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rym_albums (
                    album_id     UUID PRIMARY KEY REFERENCES albums(id) ON DELETE CASCADE,
                    rym_url      VARCHAR,
                    rym_rating   FLOAT,
                    rym_votes    INTEGER DEFAULT 0,
                    rym_lists    INTEGER DEFAULT 0,
                    genres       JSONB DEFAULT '[]',
                    descriptors  JSONB DEFAULT '[]',
                    rating_std   FLOAT,
                    fetched_at   TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_rym_albums_rating ON rym_albums(rym_rating)")

            # RYM genre taxonomy
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rym_genres (
                    id           SERIAL PRIMARY KEY,
                    name         VARCHAR UNIQUE NOT NULL,
                    parent_name  VARCHAR,
                    is_primary   BOOLEAN DEFAULT false
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rym_album_genres (
                    album_id     UUID REFERENCES albums(id) ON DELETE CASCADE,
                    genre_id     INTEGER REFERENCES rym_genres(id) ON DELETE CASCADE,
                    position     INTEGER DEFAULT 0,
                    vote_count   INTEGER DEFAULT 0,
                    PRIMARY KEY (album_id, genre_id)
                )
            """)

            # Album co-occurrence from RYM user lists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rym_album_adjacency (
                    album_a_id   UUID REFERENCES albums(id) ON DELETE CASCADE,
                    album_b_id   UUID REFERENCES albums(id) ON DELETE CASCADE,
                    co_occurrence INTEGER DEFAULT 1,
                    PRIMARY KEY (album_a_id, album_b_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_rym_adjacency_a ON rym_album_adjacency(album_a_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_rym_adjacency_b ON rym_album_adjacency(album_b_id)")

            # RYM scrape cache (raw HTML)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rym_scrape_cache (
                    url          VARCHAR PRIMARY KEY,
                    html         TEXT,
                    fetched_at   TIMESTAMPTZ DEFAULT now()
                )
            """)

            # True original release dates (multi-source verified)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS album_release_dates (
                    album_id        UUID PRIMARY KEY REFERENCES albums(id) ON DELETE CASCADE,
                    original_year   INTEGER,
                    original_month  INTEGER,
                    original_day    INTEGER,
                    precision       VARCHAR(5) DEFAULT 'year',
                    confidence      FLOAT DEFAULT 0.0,
                    primary_source  VARCHAR(20),
                    country         VARCHAR(50),
                    label           VARCHAR(200),
                    format          VARCHAR(50),
                    catalog_number  VARCHAR(100),
                    evidence        JSONB DEFAULT '{}',
                    resolved_at     TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_album_release_dates_year ON album_release_dates(original_year)")

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

        # Audio features
        cur.execute("SELECT COUNT(*) FROM track_audio_features")
        stats["tracks_with_audio_features"] = cur.fetchone()[0]

        # Genre manifold probabilities
        cur.execute("SAVEPOINT sp_genre_probs")
        try:
            cur.execute("SELECT COUNT(*) FROM track_genre_probabilities")
            stats["tracks_with_genre_probs"] = cur.fetchone()[0]
            cur.execute("RELEASE SAVEPOINT sp_genre_probs")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT sp_genre_probs")
            stats["tracks_with_genre_probs"] = 0

        # Album legitimacy & banger flags
        cur.execute("SAVEPOINT sp_legitimacy")
        try:
            cur.execute("SELECT COUNT(*) FROM album_legitimacy")
            stats["albums_with_legitimacy"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM track_banger_flags WHERE banger_score > 0")
            stats["tracks_with_banger_flags"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM lastfm_stats")
            stats["tracks_with_lastfm_stats"] = cur.fetchone()[0]
            cur.execute("RELEASE SAVEPOINT sp_legitimacy")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT sp_legitimacy")
            stats["albums_with_legitimacy"] = 0
            stats["tracks_with_banger_flags"] = 0
            stats["tracks_with_lastfm_stats"] = 0

        # MusicBrainz resolution
        cur.execute("SAVEPOINT sp_musicbrainz")
        try:
            cur.execute("SELECT COUNT(*) FROM artists WHERE musicbrainz_id IS NOT NULL")
            stats["artists_with_mbid"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM albums WHERE musicbrainz_id IS NOT NULL")
            stats["albums_with_mbid"] = cur.fetchone()[0]
            cur.execute("RELEASE SAVEPOINT sp_musicbrainz")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT sp_musicbrainz")
            stats["artists_with_mbid"] = 0
            stats["albums_with_mbid"] = 0

        # Release date resolution
        cur.execute("SAVEPOINT sp_release_dates")
        try:
            cur.execute("SELECT COUNT(*) FROM album_release_dates")
            stats["albums_with_release_dates"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM album_release_dates WHERE confidence >= 0.8")
            stats["albums_high_confidence_dates"] = cur.fetchone()[0]
            cur.execute("RELEASE SAVEPOINT sp_release_dates")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT sp_release_dates")
            stats["albums_with_release_dates"] = 0
            stats["albums_high_confidence_dates"] = 0

        # RYM enrichment
        cur.execute("SAVEPOINT sp_rym")
        try:
            cur.execute("SELECT COUNT(*) FROM rym_albums")
            stats["albums_with_rym"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM rym_album_adjacency")
            stats["rym_adjacency_pairs"] = cur.fetchone()[0]
            cur.execute("RELEASE SAVEPOINT sp_rym")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT sp_rym")
            stats["albums_with_rym"] = 0
            stats["rym_adjacency_pairs"] = 0

        # IVFFlat index status
        cur.execute("""
            SELECT COUNT(*) FROM pg_indexes
            WHERE tablename = 'track_embeddings' AND indexname = 'idx_embeddings_vector'
        """)
        stats["vector_index_built"] = cur.fetchone()[0] > 0

        return stats


# ============================================================================
# Observatory Stats (cached)
# ============================================================================

_observatory_cache: dict = {"data": None, "computed_at": 0.0}
_OBSERVATORY_TTL = 3600  # 1 hour


def get_observatory_stats(force_refresh: bool = False) -> dict:
    """Compute comprehensive collection statistics for the observatory page.

    Results are cached in-memory for 1 hour to avoid repeated expensive queries.
    """
    now = time.time()
    if (
        not force_refresh
        and _observatory_cache["data"] is not None
        and (now - _observatory_cache["computed_at"]) < _OBSERVATORY_TTL
    ):
        return _observatory_cache["data"]

    stats = _compute_observatory_stats()
    _observatory_cache["data"] = stats
    _observatory_cache["computed_at"] = time.time()
    return stats


def _compute_observatory_stats() -> dict:
    """Run all observatory SQL queries in a single connection."""
    result: dict = {}

    with get_connection() as conn:
        with conn.cursor() as cur:
            # ── 1. Collection overview ──────────────────────────────────
            collection: dict = {}

            cur.execute("SELECT COUNT(*) FROM tracks")
            collection["total_tracks"] = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM artists")
            collection["total_artists"] = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM albums")
            collection["total_albums"] = cur.fetchone()[0]

            cur.execute("SELECT COALESCE(SUM(duration_ms), 0) FROM tracks")
            collection["total_duration_ms"] = cur.fetchone()[0]

            cur.execute("""
                SELECT COALESCE(AVG(duration_ms), 0),
                       COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms), 0)
                FROM tracks
            """)
            row = cur.fetchone()
            collection["avg_duration_ms"] = float(row[0])
            collection["median_duration_ms"] = float(row[1])

            cur.execute("""
                SELECT COALESCE(AVG(track_count), 0) FROM (
                    SELECT COUNT(*) as track_count FROM track_artists
                    WHERE role = 'primary' GROUP BY artist_id
                ) sub
            """)
            collection["avg_tracks_per_artist"] = round(float(cur.fetchone()[0]), 1)

            cur.execute("""
                SELECT COALESCE(AVG(track_count), 0) FROM (
                    SELECT COUNT(*) as track_count FROM track_albums GROUP BY album_id
                ) sub
            """)
            collection["avg_tracks_per_album"] = round(float(cur.fetchone()[0]), 1)

            cur.execute("""
                SELECT COALESCE(SUM(size), 0)
                FROM track_files WHERE missing_since IS NULL
            """)
            collection["total_file_size_bytes"] = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM track_files WHERE missing_since IS NULL")
            collection["total_files"] = cur.fetchone()[0]

            result["collection"] = collection

            # ── 2. Format breakdown ─────────────────────────────────────
            cur.execute("""
                SELECT LOWER(format) as fmt, COUNT(*) as cnt
                FROM track_files WHERE missing_since IS NULL
                GROUP BY LOWER(format) ORDER BY cnt DESC
            """)
            result["formats"] = [{"format": r[0], "count": r[1]} for r in cur.fetchall()]

            # ── 3. Timeline (decades + years) ───────────────────────────
            cur.execute("""
                SELECT (year / 10) * 10 as decade, COUNT(*) as cnt
                FROM tracks WHERE year IS NOT NULL AND year >= 1900 AND year <= 2030
                GROUP BY decade ORDER BY decade
            """)
            result["decades"] = [{"decade": r[0], "count": r[1]} for r in cur.fetchall()]

            cur.execute("""
                SELECT year, COUNT(*) as cnt
                FROM tracks WHERE year IS NOT NULL AND year >= 1900 AND year <= 2030
                GROUP BY year ORDER BY year
            """)
            result["years"] = [{"year": r[0], "count": r[1]} for r in cur.fetchall()]

            cur.execute("""
                SELECT MIN(year), MAX(year)
                FROM tracks WHERE year IS NOT NULL AND year >= 1900
            """)
            row = cur.fetchone()
            result["oldest_year"] = row[0]
            result["newest_year"] = row[1]

            # Oldest/newest tracks with details
            cur.execute("""
                SELECT t.title, a.name as artist, t.year
                FROM tracks t
                JOIN track_artists ta ON t.id = ta.track_id AND ta.role = 'primary'
                JOIN artists a ON ta.artist_id = a.id
                WHERE t.year IS NOT NULL AND t.year >= 1900
                ORDER BY t.year ASC, t.title LIMIT 5
            """)
            result["oldest_tracks"] = [
                {"title": r[0], "artist": r[1], "year": r[2]} for r in cur.fetchall()
            ]

            cur.execute("""
                SELECT t.title, a.name as artist, t.year
                FROM tracks t
                JOIN track_artists ta ON t.id = ta.track_id AND ta.role = 'primary'
                JOIN artists a ON ta.artist_id = a.id
                WHERE t.year IS NOT NULL AND t.year >= 1900
                ORDER BY t.year DESC, t.title LIMIT 5
            """)
            result["newest_tracks"] = [
                {"title": r[0], "artist": r[1], "year": r[2]} for r in cur.fetchall()
            ]

            # Decade concentration insight
            cur.execute("""
                SELECT (year / 10) * 10 as decade, COUNT(*) as cnt
                FROM tracks WHERE year IS NOT NULL AND year >= 1900
                GROUP BY decade ORDER BY cnt DESC LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                total_with_year_q = "SELECT COUNT(*) FROM tracks WHERE year IS NOT NULL AND year >= 1900"
                cur.execute(total_with_year_q)
                total_with_year = cur.fetchone()[0]
                result["dominant_decade"] = {
                    "decade": row[0],
                    "count": row[1],
                    "percentage": round(row[1] / total_with_year * 100, 1) if total_with_year > 0 else 0,
                }
            else:
                result["dominant_decade"] = None

            # ── 4. Tag intelligence ─────────────────────────────────────
            # Top 50 tags by track count (via artist->tag association)
            cur.execute("""
                SELECT lt.name,
                       COUNT(DISTINCT ta.track_id) as track_count,
                       COUNT(DISTINCT alt.artist_id) as artist_count
                FROM lastfm_tags lt
                JOIN artist_lastfm_tags alt ON lt.id = alt.tag_id
                JOIN track_artists ta ON ta.artist_id = alt.artist_id AND ta.role = 'primary'
                GROUP BY lt.id, lt.name
                ORDER BY track_count DESC
                LIMIT 50
            """)
            result["top_tags"] = [
                {"name": r[0], "track_count": r[1], "artist_count": r[2]}
                for r in cur.fetchall()
            ]

            # Rare / obscure tags (1-3 artists only)
            cur.execute("""
                SELECT lt.name, COUNT(DISTINCT alt.artist_id) as artist_count
                FROM lastfm_tags lt
                JOIN artist_lastfm_tags alt ON lt.id = alt.tag_id
                GROUP BY lt.id, lt.name
                HAVING COUNT(DISTINCT alt.artist_id) BETWEEN 1 AND 3
                ORDER BY lt.name
                LIMIT 50
            """)
            result["rare_tags"] = [
                {"name": r[0], "artist_count": r[1]} for r in cur.fetchall()
            ]

            # Tag co-occurrence (top artist-tag pairs that appear together)
            cur.execute("""
                SELECT t1.name as tag1, t2.name as tag2, COUNT(DISTINCT a1.artist_id) as shared_artists
                FROM artist_lastfm_tags a1
                JOIN artist_lastfm_tags a2 ON a1.artist_id = a2.artist_id AND a1.tag_id < a2.tag_id
                JOIN lastfm_tags t1 ON a1.tag_id = t1.id
                JOIN lastfm_tags t2 ON a2.tag_id = t2.id
                WHERE a1.weight >= 50 AND a2.weight >= 50
                GROUP BY t1.name, t2.name
                HAVING COUNT(DISTINCT a1.artist_id) >= 5
                ORDER BY shared_artists DESC
                LIMIT 30
            """)
            result["tag_pairs"] = [
                {"tag1": r[0], "tag2": r[1], "shared_artists": r[2]}
                for r in cur.fetchall()
            ]

            # ── 5. Artist intelligence ──────────────────────────────────
            # Top 20 by track count
            cur.execute("""
                SELECT a.name, COUNT(ta.track_id) as track_count
                FROM artists a
                JOIN track_artists ta ON a.id = ta.artist_id AND ta.role = 'primary'
                GROUP BY a.id, a.name
                ORDER BY track_count DESC
                LIMIT 20
            """)
            result["top_artists_by_tracks"] = [
                {"name": r[0], "count": r[1]} for r in cur.fetchall()
            ]

            # Top 20 by total playtime
            cur.execute("""
                SELECT a.name, SUM(t.duration_ms) as total_ms
                FROM artists a
                JOIN track_artists ta ON a.id = ta.artist_id AND ta.role = 'primary'
                JOIN tracks t ON t.id = ta.track_id
                GROUP BY a.id, a.name
                ORDER BY total_ms DESC
                LIMIT 20
            """)
            result["top_artists_by_playtime"] = [
                {"name": r[0], "duration_ms": r[1]} for r in cur.fetchall()
            ]

            # Top 20 by album count
            cur.execute("""
                SELECT a.name, COUNT(DISTINCT aa.album_id) as album_count
                FROM artists a
                JOIN album_artists aa ON a.id = aa.artist_id
                GROUP BY a.id, a.name
                ORDER BY album_count DESC
                LIMIT 20
            """)
            result["top_artists_by_albums"] = [
                {"name": r[0], "count": r[1]} for r in cur.fetchall()
            ]

            # One-track artists
            cur.execute("""
                SELECT COUNT(*) FROM (
                    SELECT ta.artist_id FROM track_artists ta
                    WHERE ta.role = 'primary'
                    GROUP BY ta.artist_id HAVING COUNT(ta.track_id) = 1
                ) sub
            """)
            one_track_count = cur.fetchone()[0]
            result["one_track_artists"] = {
                "count": one_track_count,
                "percentage": round(one_track_count / collection["total_artists"] * 100, 1)
                if collection["total_artists"] > 0 else 0,
            }

            # ── 6. Album statistics ─────────────────────────────────────
            # Albums with most tracks
            cur.execute("""
                SELECT al.title,
                       (SELECT string_agg(a.name, ', ')
                        FROM album_artists aa JOIN artists a ON aa.artist_id = a.id
                        WHERE aa.album_id = al.id) as artist,
                       COUNT(tl.track_id) as track_count
                FROM albums al
                JOIN track_albums tl ON al.id = tl.album_id
                GROUP BY al.id, al.title
                ORDER BY track_count DESC
                LIMIT 20
            """)
            result["albums_most_tracks"] = [
                {"title": r[0], "artist": r[1], "track_count": r[2]} for r in cur.fetchall()
            ]

            # Longest albums by total duration
            cur.execute("""
                SELECT al.title,
                       (SELECT string_agg(a.name, ', ')
                        FROM album_artists aa JOIN artists a ON aa.artist_id = a.id
                        WHERE aa.album_id = al.id) as artist,
                       SUM(t.duration_ms) as total_ms,
                       COUNT(tl.track_id) as track_count
                FROM albums al
                JOIN track_albums tl ON al.id = tl.album_id
                JOIN tracks t ON t.id = tl.track_id
                GROUP BY al.id, al.title
                ORDER BY total_ms DESC
                LIMIT 20
            """)
            result["albums_longest"] = [
                {"title": r[0], "artist": r[1], "duration_ms": r[2], "track_count": r[3]}
                for r in cur.fetchall()
            ]

            # Shortest albums (at least 2 tracks to exclude singles)
            cur.execute("""
                SELECT al.title,
                       (SELECT string_agg(a.name, ', ')
                        FROM album_artists aa JOIN artists a ON aa.artist_id = a.id
                        WHERE aa.album_id = al.id) as artist,
                       SUM(t.duration_ms) as total_ms,
                       COUNT(tl.track_id) as track_count
                FROM albums al
                JOIN track_albums tl ON al.id = tl.album_id
                JOIN tracks t ON t.id = tl.track_id
                GROUP BY al.id, al.title
                HAVING COUNT(tl.track_id) >= 2
                ORDER BY total_ms ASC
                LIMIT 20
            """)
            result["albums_shortest"] = [
                {"title": r[0], "artist": r[1], "duration_ms": r[2], "track_count": r[3]}
                for r in cur.fetchall()
            ]

            # ── 7. Profile fingerprint (4D) ─────────────────────────────
            cur.execute("SELECT COUNT(*) FROM track_profiles")
            profile_count = cur.fetchone()[0]

            if profile_count > 0:
                cur.execute("""
                    SELECT AVG(energy), AVG(darkness), AVG(tempo), AVG(texture)
                    FROM track_profiles
                """)
                row = cur.fetchone()
                result["profile_averages"] = {
                    "energy": round(float(row[0]), 3),
                    "darkness": round(float(row[1]), 3),
                    "tempo": round(float(row[2]), 3),
                    "texture": round(float(row[3]), 3),
                    "count": profile_count,
                }

                # Distribution histograms (10 bins per dimension)
                distributions = {}
                for dim in ("energy", "darkness", "tempo", "texture"):
                    cur.execute(f"""
                        SELECT FLOOR({dim} * 10)::int as bin, COUNT(*) as cnt
                        FROM track_profiles
                        WHERE {dim} IS NOT NULL
                        GROUP BY bin ORDER BY bin
                    """)
                    bins = {r[0]: r[1] for r in cur.fetchall()}
                    distributions[dim] = [
                        {"bin": i / 10, "label": f"{i/10:.1f}-{(i+1)/10:.1f}", "count": bins.get(i, 0)}
                        for i in range(10)
                    ]
                result["profile_distributions"] = distributions
            else:
                result["profile_averages"] = None
                result["profile_distributions"] = None

            # ── 8. Scene clusters ───────────────────────────────────────
            cur.execute("SAVEPOINT sp_obs_clusters")
            try:
                cur.execute("""
                    SELECT sc.id, sc.name, sc.size
                    FROM scene_clusters sc
                    ORDER BY sc.size DESC
                """)
                clusters = []
                for crow in cur.fetchall():
                    cluster_id, cluster_name, cluster_size = crow
                    # Top 8 artists per cluster
                    cur.execute("""
                        SELECT a.name, ac.weight
                        FROM artist_clusters ac
                        JOIN artists a ON ac.artist_id = a.id
                        WHERE ac.cluster_id = %s
                        ORDER BY ac.weight DESC
                        LIMIT 8
                    """, (cluster_id,))
                    top_artists = [{"name": r[0], "weight": round(float(r[1]), 2)} for r in cur.fetchall()]

                    # Top tags for this cluster's artists
                    cur.execute("""
                        SELECT lt.name, COUNT(DISTINCT ac.artist_id) as cnt
                        FROM artist_clusters ac
                        JOIN artist_lastfm_tags alt ON ac.artist_id = alt.artist_id
                        JOIN lastfm_tags lt ON alt.tag_id = lt.id
                        WHERE ac.cluster_id = %s AND alt.weight >= 50
                        GROUP BY lt.name
                        ORDER BY cnt DESC
                        LIMIT 5
                    """, (cluster_id,))
                    top_tags = [{"name": r[0], "count": r[1]} for r in cur.fetchall()]

                    clusters.append({
                        "id": cluster_id,
                        "name": cluster_name,
                        "size": cluster_size,
                        "top_artists": top_artists,
                        "top_tags": top_tags,
                    })
                cur.execute("RELEASE SAVEPOINT sp_obs_clusters")
                result["clusters"] = clusters
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT sp_obs_clusters")
                result["clusters"] = []

            # ── 9. Audio features ───────────────────────────────────────
            cur.execute("SELECT COUNT(*) FROM track_audio_features")
            audio_count = cur.fetchone()[0]

            if audio_count > 0:
                # BPM distribution
                cur.execute("""
                    SELECT FLOOR(bpm / 10) * 10 as bpm_bin, COUNT(*) as cnt
                    FROM track_audio_features
                    WHERE bpm IS NOT NULL AND bpm > 0
                    GROUP BY bpm_bin ORDER BY bpm_bin
                """)
                result["bpm_distribution"] = [
                    {"bpm": int(r[0]), "count": r[1]} for r in cur.fetchall()
                ]

                # Key distribution
                cur.execute("""
                    SELECT key_estimate, COUNT(*) as cnt
                    FROM track_audio_features
                    WHERE key_estimate IS NOT NULL
                    GROUP BY key_estimate ORDER BY cnt DESC
                """)
                result["key_distribution"] = [
                    {"key": r[0], "count": r[1]} for r in cur.fetchall()
                ]

                # Averages
                cur.execute("""
                    SELECT AVG(bpm), AVG(loudness_rms), AVG(spectral_centroid)
                    FROM track_audio_features
                """)
                row = cur.fetchone()
                result["audio_averages"] = {
                    "avg_bpm": round(float(row[0] or 0), 1),
                    "avg_loudness_rms": round(float(row[1] or 0), 4),
                    "avg_spectral_centroid": round(float(row[2] or 0), 1),
                    "analyzed_count": audio_count,
                }
            else:
                result["bpm_distribution"] = []
                result["key_distribution"] = []
                result["audio_averages"] = None

            # ── 10. Generation stats ────────────────────────────────────
            cur.execute("SELECT COUNT(*) FROM generated_playlists")
            result["total_playlists"] = cur.fetchone()[0]

            cur.execute("""
                SELECT arc_type, COUNT(*) as cnt, AVG(generation_time_ms) as avg_time
                FROM playlist_generation_log
                WHERE arc_type IS NOT NULL
                GROUP BY arc_type ORDER BY cnt DESC
            """)
            result["arc_type_breakdown"] = [
                {"arc_type": r[0], "count": r[1], "avg_time_ms": round(float(r[2] or 0))}
                for r in cur.fetchall()
            ]

            # Most-used tracks in playlists
            cur.execute("""
                SELECT t.title, a.name as artist, tu.usage_count
                FROM track_usage tu
                JOIN tracks t ON tu.track_id = t.id
                JOIN track_artists ta ON t.id = ta.track_id AND ta.role = 'primary'
                JOIN artists a ON ta.artist_id = a.id
                ORDER BY tu.usage_count DESC
                LIMIT 20
            """)
            result["most_used_tracks"] = [
                {"title": r[0], "artist": r[1], "usage_count": r[2]}
                for r in cur.fetchall()
            ]

            # ── 12. Cultural map (gravity + tag evolution + genre purity) ─
            cultural_map: dict = {}

            # Cultural gravity: unique artists per tag (top 50)
            cur.execute("""
                SELECT lt.name, COUNT(DISTINCT alt.artist_id) AS artist_count
                FROM artist_lastfm_tags alt
                JOIN lastfm_tags lt ON lt.id = alt.tag_id
                WHERE alt.weight >= 30
                GROUP BY lt.id, lt.name
                ORDER BY artist_count DESC
                LIMIT 50
            """)
            cultural_map["cultural_gravity"] = [
                {"tag": r[0], "artist_count": r[1]} for r in cur.fetchall()
            ]

            # Tag evolution timeline: top 5 tags per decade
            cur.execute("""
                SELECT decade, tag, artist_count FROM (
                    SELECT
                        (t.year / 10) * 10 AS decade,
                        lt.name AS tag,
                        COUNT(DISTINCT ta.artist_id) AS artist_count,
                        ROW_NUMBER() OVER (
                            PARTITION BY (t.year / 10) * 10
                            ORDER BY COUNT(DISTINCT ta.artist_id) DESC
                        ) AS rn
                    FROM tracks t
                    JOIN track_artists ta ON ta.track_id = t.id AND ta.role = 'primary'
                    JOIN artist_lastfm_tags alt ON alt.artist_id = ta.artist_id
                    JOIN lastfm_tags lt ON lt.id = alt.tag_id
                    WHERE t.year IS NOT NULL AND t.year >= 1900 AND alt.weight >= 30
                    GROUP BY decade, lt.name
                ) sub
                WHERE rn <= 5
                ORDER BY decade, artist_count DESC
            """)
            # Group by decade
            tag_evolution: dict[int, list] = {}
            for r in cur.fetchall():
                decade = r[0]
                if decade not in tag_evolution:
                    tag_evolution[decade] = []
                tag_evolution[decade].append({"tag": r[1], "artist_count": r[2]})
            cultural_map["tag_evolution"] = [
                {"decade": d, "tags": tags} for d, tags in sorted(tag_evolution.items())
            ]

            # Genre purity vs hybridization
            cur.execute("""
                SELECT bucket, COUNT(*) AS artist_count FROM (
                    SELECT
                        CASE
                            WHEN cnt = 1 THEN 'pure'
                            WHEN cnt BETWEEN 2 AND 3 THEN 'hybrid'
                            ELSE 'highly_hybrid'
                        END AS bucket
                    FROM (
                        SELECT alt.artist_id, COUNT(DISTINCT alt.tag_id) AS cnt
                        FROM artist_lastfm_tags alt
                        WHERE alt.weight >= 30
                        GROUP BY alt.artist_id
                    ) tag_counts
                ) sub
                GROUP BY bucket
            """)
            purity_map = {r[0]: r[1] for r in cur.fetchall()}
            total_tagged = sum(purity_map.values()) or 1
            cultural_map["genre_purity"] = {
                "pure": purity_map.get("pure", 0),
                "hybrid": purity_map.get("hybrid", 0),
                "highly_hybrid": purity_map.get("highly_hybrid", 0),
                "total_tagged_artists": total_tagged,
                "pure_pct": round(purity_map.get("pure", 0) / total_tagged * 100, 1),
                "hybrid_pct": round(purity_map.get("hybrid", 0) / total_tagged * 100, 1),
                "highly_hybrid_pct": round(purity_map.get("highly_hybrid", 0) / total_tagged * 100, 1),
            }

            result["cultural_map"] = cultural_map

            # ── 13. Darkness index ──────────────────────────────────────
            darkness_index: dict = {}

            # Title-based darkness keywords
            dark_keywords = [
                'dark', 'death', 'black', 'blood', 'hell', 'evil',
                'night', 'doom', 'shadow', 'abyss', 'grave', 'corpse',
                'satan', 'demon', 'chaos', 'plague', 'void', 'funeral',
                'sorrow', 'hatred', 'cursed', 'witch', 'occult', 'tomb',
            ]
            keyword_placeholders = ", ".join(["%s"] * len(dark_keywords))
            cur.execute(f"""
                SELECT kw.word, COUNT(*) AS cnt
                FROM UNNEST(ARRAY[{keyword_placeholders}]::text[]) AS kw(word)
                CROSS JOIN LATERAL (
                    SELECT 1 FROM tracks t
                    WHERE LOWER(t.title) LIKE '%%' || kw.word || '%%'
                ) matches
                GROUP BY kw.word ORDER BY cnt DESC
            """, dark_keywords)
            keyword_counts = [{"word": r[0], "count": r[1]} for r in cur.fetchall()]
            total_dark_titles = 0
            if keyword_counts:
                # Count distinct tracks matching any keyword
                like_clauses = " OR ".join(["LOWER(title) LIKE %s"] * len(dark_keywords))
                like_params = [f"%{kw}%" for kw in dark_keywords]
                cur.execute(f"""
                    SELECT COUNT(*) FROM tracks WHERE {like_clauses}
                """, like_params)
                total_dark_titles = cur.fetchone()[0]

            darkness_index["keyword_counts"] = keyword_counts
            darkness_index["total_dark_title_tracks"] = total_dark_titles
            darkness_index["total_tracks"] = collection["total_tracks"]
            darkness_index["dark_title_pct"] = (
                round(total_dark_titles / collection["total_tracks"] * 100, 1)
                if collection["total_tracks"] > 0 else 0
            )

            # Profile-based darkness distribution
            if profile_count > 0:
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE darkness >= 0.8) AS very_dark,
                        COUNT(*) FILTER (WHERE darkness >= 0.6 AND darkness < 0.8) AS dark,
                        COUNT(*) FILTER (WHERE darkness >= 0.4 AND darkness < 0.6) AS neutral,
                        COUNT(*) FILTER (WHERE darkness >= 0.2 AND darkness < 0.4) AS light,
                        COUNT(*) FILTER (WHERE darkness < 0.2) AS very_light,
                        ROUND(AVG(darkness)::numeric, 3) AS avg_darkness,
                        COUNT(*) AS total
                    FROM track_profiles
                """)
                row = cur.fetchone()
                darkness_index["profile_distribution"] = {
                    "very_dark": row[0], "dark": row[1], "neutral": row[2],
                    "light": row[3], "very_light": row[4],
                    "avg_darkness": float(row[5]), "total": row[6],
                }

                # Top 20 darkest artists (min 3 tracks)
                cur.execute("""
                    SELECT a.name, ROUND(AVG(tp.darkness)::numeric, 3) AS avg_darkness,
                           COUNT(*) AS track_count
                    FROM track_profiles tp
                    JOIN track_artists ta ON ta.track_id = tp.track_id AND ta.role = 'primary'
                    JOIN artists a ON a.id = ta.artist_id
                    GROUP BY a.id, a.name
                    HAVING COUNT(*) >= 3
                    ORDER BY avg_darkness DESC
                    LIMIT 20
                """)
                darkness_index["darkest_artists"] = [
                    {"name": r[0], "avg_darkness": float(r[1]), "track_count": r[2]}
                    for r in cur.fetchall()
                ]
            else:
                darkness_index["profile_distribution"] = None
                darkness_index["darkest_artists"] = []

            result["darkness_index"] = darkness_index

            # ── 14. Longform compositions + title archetypes ────────────
            longform: dict = {}

            # Duration thresholds
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE duration_ms >= 600000) AS over_10min,
                    COUNT(*) FILTER (WHERE duration_ms >= 900000) AS over_15min,
                    COUNT(*) FILTER (WHERE duration_ms >= 1200000) AS over_20min,
                    COUNT(*) FILTER (WHERE duration_ms >= 1800000) AS over_30min,
                    COUNT(*) AS total
                FROM tracks
            """)
            row = cur.fetchone()
            longform["thresholds"] = {
                "over_10min": row[0], "over_15min": row[1],
                "over_20min": row[2], "over_30min": row[3],
                "total_tracks": row[4],
            }

            # Top 20 longest tracks
            cur.execute("""
                SELECT t.title, a.name AS artist, t.duration_ms
                FROM tracks t
                JOIN track_artists ta ON ta.track_id = t.id AND ta.role = 'primary'
                JOIN artists a ON a.id = ta.artist_id
                ORDER BY t.duration_ms DESC
                LIMIT 20
            """)
            longform["longest_tracks"] = [
                {"title": r[0], "artist": r[1], "duration_ms": r[2]}
                for r in cur.fetchall()
            ]

            # Title archetypes
            cur.execute("""
                SELECT pattern, COUNT(*) AS cnt FROM (
                    SELECT CASE
                        WHEN LOWER(title) ~ '^intro($|[^a-z])' THEN 'Intro'
                        WHEN LOWER(title) ~ '(^|[^a-z])interlude($|[^a-z])' THEN 'Interlude'
                        WHEN LOWER(title) ~ '^outro($|[^a-z])' THEN 'Outro'
                        WHEN LOWER(title) ~ 'part\s+[ivxlcdm0-9]+' THEN 'Part I/II/III...'
                        WHEN LOWER(title) ~ '\(live' OR LOWER(title) ~ 'live at\s' THEN 'Live'
                        WHEN LOWER(title) ~ '\(demo\)|\sdemo$|demo\s+\d' THEN 'Demo'
                        WHEN LOWER(title) ~ '\(remix\)|\sremix$|\sremix\s' THEN 'Remix'
                        WHEN LOWER(title) ~ '\(acoustic\)|\sacoustic' THEN 'Acoustic'
                        WHEN LOWER(title) ~ 'untitled' THEN 'Untitled'
                        WHEN LOWER(title) ~ '^prologue($|[^a-z])' THEN 'Prologue'
                        WHEN LOWER(title) ~ '^epilogue($|[^a-z])' THEN 'Epilogue'
                        WHEN LOWER(title) ~ '^prelude($|[^a-z])' THEN 'Prelude'
                        ELSE NULL
                    END AS pattern
                    FROM tracks
                ) sub
                WHERE pattern IS NOT NULL
                GROUP BY pattern ORDER BY cnt DESC
            """)
            longform["title_archetypes"] = [
                {"pattern": r[0], "count": r[1]} for r in cur.fetchall()
            ]

            result["longform"] = longform

            # ── 15. Collection archaeology ──────────────────────────────
            archaeology: dict = {}

            # Compilation contamination
            cur.execute("""
                SELECT COUNT(DISTINCT ta2.track_id) AS compilation_tracks
                FROM artists a
                JOIN track_artists ta2 ON ta2.artist_id = a.id
                WHERE LOWER(a.name) IN ('various artists', 'various', 'va')
            """)
            comp_tracks = cur.fetchone()[0]
            archaeology["compilation"] = {
                "compilation_tracks": comp_tracks,
                "total_tracks": collection["total_tracks"],
                "compilation_pct": (
                    round(comp_tracks / collection["total_tracks"] * 100, 1)
                    if collection["total_tracks"] > 0 else 0
                ),
            }

            # Artists discovered through compilations
            cur.execute("""
                SELECT DISTINCT a_primary.name, COUNT(DISTINCT t.id) AS track_count
                FROM tracks t
                JOIN track_artists ta_primary ON ta_primary.track_id = t.id
                    AND ta_primary.role = 'primary'
                JOIN artists a_primary ON a_primary.id = ta_primary.artist_id
                JOIN track_albums tal ON tal.track_id = t.id
                JOIN albums alb ON alb.id = tal.album_id
                JOIN album_artists aa ON aa.album_id = alb.id
                JOIN artists va ON va.id = aa.artist_id
                    AND LOWER(va.name) IN ('various artists', 'various', 'va')
                WHERE LOWER(a_primary.name) NOT IN ('various artists', 'various', 'va')
                GROUP BY a_primary.id, a_primary.name
                ORDER BY track_count DESC
                LIMIT 20
            """)
            archaeology["compilation_artists"] = [
                {"name": r[0], "track_count": r[1]} for r in cur.fetchall()
            ]

            # Forgotten tracks (never used in any playlist)
            cur.execute("""
                SELECT COUNT(*) FROM tracks t
                WHERE NOT EXISTS (
                    SELECT 1 FROM track_usage tu WHERE tu.track_id = t.id
                )
            """)
            forgotten_count = cur.fetchone()[0]
            archaeology["forgotten"] = {
                "forgotten_count": forgotten_count,
                "total_tracks": collection["total_tracks"],
                "forgotten_pct": (
                    round(forgotten_count / collection["total_tracks"] * 100, 1)
                    if collection["total_tracks"] > 0 else 0
                ),
            }

            # Random sample of forgotten tracks
            cur.execute("""
                SELECT t.title, a.name AS artist, t.year, t.duration_ms
                FROM tracks t
                JOIN track_artists ta ON ta.track_id = t.id AND ta.role = 'primary'
                JOIN artists a ON a.id = ta.artist_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM track_usage tu WHERE tu.track_id = t.id
                )
                ORDER BY RANDOM()
                LIMIT 10
            """)
            archaeology["forgotten_sample"] = [
                {"title": r[0], "artist": r[1], "year": r[2], "duration_ms": r[3]}
                for r in cur.fetchall()
            ]

            # Temporal listening bias (release decade vs playlist usage share)
            cur.execute("""
                SELECT
                    (t.year / 10) * 10 AS decade,
                    COUNT(DISTINCT t.id) AS library_count,
                    COALESCE(SUM(tu.usage_count), 0) AS total_uses
                FROM tracks t
                LEFT JOIN track_usage tu ON tu.track_id = t.id
                WHERE t.year IS NOT NULL AND t.year >= 1900
                GROUP BY decade ORDER BY decade
            """)
            temporal_rows = cur.fetchall()
            total_library = sum(r[1] for r in temporal_rows) or 1
            total_uses = sum(r[2] for r in temporal_rows) or 1
            archaeology["temporal_bias"] = [
                {
                    "decade": r[0],
                    "library_count": r[1],
                    "library_pct": round(r[1] / total_library * 100, 1),
                    "usage_count": r[2],
                    "usage_pct": round(r[2] / total_uses * 100, 1),
                }
                for r in temporal_rows
            ]

            result["archaeology"] = archaeology

            # ── 16. Genre gateways (bridge artists) ─────────────────────
            gateways: dict = {}

            # Most cross-genre artists (4+ tags)
            cur.execute("""
                SELECT a.name,
                    COUNT(DISTINCT alt.tag_id) AS tag_count,
                    ARRAY_AGG(DISTINCT lt.name ORDER BY lt.name) AS tags
                FROM artists a
                JOIN artist_lastfm_tags alt ON alt.artist_id = a.id AND alt.weight >= 30
                JOIN lastfm_tags lt ON lt.id = alt.tag_id
                GROUP BY a.id, a.name
                HAVING COUNT(DISTINCT alt.tag_id) >= 5
                ORDER BY tag_count DESC
                LIMIT 30
            """)
            gateways["bridge_artists"] = [
                {"name": r[0], "tag_count": r[1], "tags": r[2]}
                for r in cur.fetchall()
            ]

            # Genre bridge pairs: two scene-level tags connected by shared artists
            cur.execute("""
                WITH scene_tags AS (
                    SELECT lt.id, lt.name
                    FROM lastfm_tags lt
                    JOIN artist_lastfm_tags alt ON alt.tag_id = lt.id AND alt.weight >= 50
                    GROUP BY lt.id, lt.name
                    HAVING COUNT(DISTINCT alt.artist_id) >= 10
                )
                SELECT st1.name AS tag1, st2.name AS tag2,
                    COUNT(DISTINCT alt1.artist_id) AS bridge_count
                FROM scene_tags st1
                JOIN artist_lastfm_tags alt1 ON alt1.tag_id = st1.id AND alt1.weight >= 50
                JOIN artist_lastfm_tags alt2 ON alt2.artist_id = alt1.artist_id
                    AND alt2.tag_id != alt1.tag_id AND alt2.weight >= 50
                JOIN scene_tags st2 ON st2.id = alt2.tag_id AND st2.id > st1.id
                GROUP BY st1.name, st2.name
                HAVING COUNT(DISTINCT alt1.artist_id) >= 3
                ORDER BY bridge_count DESC
                LIMIT 30
            """)
            gateways["genre_bridges"] = [
                {"tag1": r[0], "tag2": r[1], "bridge_count": r[2]}
                for r in cur.fetchall()
            ]

            result["gateways"] = gateways

            # ── 11. Fun / weird stats ───────────────────────────────────
            fun: dict = {}

            # Longest track titles
            cur.execute("""
                SELECT t.title, LENGTH(t.title) as len, a.name as artist
                FROM tracks t
                JOIN track_artists ta ON t.id = ta.track_id AND ta.role = 'primary'
                JOIN artists a ON ta.artist_id = a.id
                ORDER BY LENGTH(t.title) DESC
                LIMIT 5
            """)
            fun["longest_titles"] = [
                {"title": r[0], "length": r[1], "artist": r[2]} for r in cur.fetchall()
            ]

            # Longest track (by duration)
            cur.execute("""
                SELECT t.title, t.duration_ms, a.name as artist
                FROM tracks t
                JOIN track_artists ta ON t.id = ta.track_id AND ta.role = 'primary'
                JOIN artists a ON ta.artist_id = a.id
                ORDER BY t.duration_ms DESC
                LIMIT 5
            """)
            fun["longest_tracks"] = [
                {"title": r[0], "duration_ms": r[1], "artist": r[2]} for r in cur.fetchall()
            ]

            # Shortest track (by duration, > 0)
            cur.execute("""
                SELECT t.title, t.duration_ms, a.name as artist
                FROM tracks t
                JOIN track_artists ta ON t.id = ta.track_id AND ta.role = 'primary'
                JOIN artists a ON ta.artist_id = a.id
                WHERE t.duration_ms > 0
                ORDER BY t.duration_ms ASC
                LIMIT 5
            """)
            fun["shortest_tracks"] = [
                {"title": r[0], "duration_ms": r[1], "artist": r[2]} for r in cur.fetchall()
            ]

            # Most common words in track titles (excluding short words)
            cur.execute("""
                SELECT word, COUNT(*) as cnt FROM (
                    SELECT LOWER(regexp_split_to_table(title, '\s+')) as word
                    FROM tracks
                ) sub
                WHERE LENGTH(word) >= 4
                GROUP BY word ORDER BY cnt DESC
                LIMIT 20
            """)
            fun["common_title_words"] = [
                {"word": r[0], "count": r[1]} for r in cur.fetchall()
            ]

            # Most common words in artist names
            cur.execute("""
                SELECT word, COUNT(*) as cnt FROM (
                    SELECT LOWER(regexp_split_to_table(name, '\s+')) as word
                    FROM artists
                ) sub
                WHERE LENGTH(word) >= 3
                GROUP BY word ORDER BY cnt DESC
                LIMIT 20
            """)
            fun["common_artist_words"] = [
                {"word": r[0], "count": r[1]} for r in cur.fetchall()
            ]

            # Longest file paths
            cur.execute("""
                SELECT path, LENGTH(path) as len
                FROM track_files
                WHERE missing_since IS NULL
                ORDER BY LENGTH(path) DESC
                LIMIT 5
            """)
            fun["longest_paths"] = [
                {"path": r[0], "length": r[1]} for r in cur.fetchall()
            ]

            # Deepest directory depth
            cur.execute("""
                SELECT path,
                       LENGTH(path) - LENGTH(REPLACE(path, '/', '')) as depth
                FROM track_files
                WHERE missing_since IS NULL
                ORDER BY depth DESC
                LIMIT 5
            """)
            fun["deepest_paths"] = [
                {"path": r[0], "depth": r[1]} for r in cur.fetchall()
            ]

            result["fun_stats"] = fun

    logger.info("Observatory stats computed successfully")
    return result


def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


def rebuild_search_vectors(progress_callback: callable = None) -> dict[str, int]:
    """Rebuild the tsvector search_vector column on all tracks.

    This enables BM25 full-text search as a retrieval channel.
    The vector is composed of:
      - Weight A: track title + primary artist name + genre names
      - Weight B: Last.fm tags (track-level if available, else artist-level fallback)
                  + RYM genres (high-resolution subgenre terms)
      - Weight C: RYM descriptors (mood/style terms like atmospheric, melancholic)

    Args:
        progress_callback: Optional (current, total, message) callback.

    Returns:
        Stats dict with counts.
    """
    stats = {"total": 0, "updated": 0}

    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Ensure the column exists
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'tracks' AND column_name = 'search_vector'
            """)
            if not cur.fetchone():
                logger.info("Adding search_vector column to tracks table")
                cur.execute("ALTER TABLE tracks ADD COLUMN search_vector tsvector")
        conn.commit()

    with get_connection() as conn:
        with conn.cursor() as cur:
            # 2. Count tracks
            cur.execute("SELECT COUNT(*) FROM tracks")
            total = cur.fetchone()[0]
            stats["total"] = total

            if total == 0:
                logger.info("No tracks to rebuild search vectors for")
                return stats

            if progress_callback:
                progress_callback(0, total, f"Rebuilding search vectors for {total} tracks...")

            # 3. Populate search_vector using artist_lastfm_tags as fallback
            #    since track_lastfm_tags typically has 0 rows.
            #    RYM genres added as Weight B (same level as Last.fm tags).
            #    RYM descriptors added as Weight C (mood/style terms).
            cur.execute("""
                UPDATE tracks t
                SET search_vector =
                    setweight(to_tsvector('simple', coalesce(t.title, '')), 'A') ||
                    setweight(to_tsvector('simple', coalesce((
                        SELECT string_agg(a.name, ' ')
                        FROM track_artists ta
                        JOIN artists a ON ta.artist_id = a.id
                        WHERE ta.track_id = t.id AND ta.role = 'primary'
                    ), '')), 'A') ||
                    setweight(to_tsvector('simple', coalesce((
                        SELECT string_agg(g.name, ' ')
                        FROM track_genres tg
                        JOIN genres g ON tg.genre_id = g.id
                        WHERE tg.track_id = t.id
                    ), '')), 'A') ||
                    setweight(to_tsvector('simple', coalesce((
                        SELECT string_agg(sub.name, ' ')
                        FROM (
                            SELECT lt.name
                            FROM lastfm_tags lt
                            JOIN track_lastfm_tags tlt ON lt.id = tlt.tag_id
                            WHERE tlt.track_id = t.id
                            ORDER BY tlt.weight DESC
                            LIMIT 20
                        ) sub
                    ), (
                        SELECT string_agg(sub2.name, ' ')
                        FROM (
                            SELECT lt2.name
                            FROM lastfm_tags lt2
                            JOIN artist_lastfm_tags alt ON lt2.id = alt.tag_id
                            JOIN track_artists ta2 ON ta2.artist_id = alt.artist_id
                            WHERE ta2.track_id = t.id
                            ORDER BY alt.weight DESC
                            LIMIT 20
                        ) sub2
                    ), '')), 'B') ||
                    setweight(to_tsvector('simple', coalesce((
                        SELECT string_agg(g, ' ')
                        FROM rym_albums ra
                        JOIN track_albums tal ON tal.album_id = ra.album_id,
                        LATERAL jsonb_array_elements_text(ra.genres) AS g
                        WHERE tal.track_id = t.id
                    ), '')), 'B') ||
                    setweight(to_tsvector('simple', coalesce((
                        SELECT string_agg(d, ' ')
                        FROM rym_albums ra
                        JOIN track_albums tal ON tal.album_id = ra.album_id,
                        LATERAL jsonb_array_elements_text(ra.descriptors) AS d
                        WHERE tal.track_id = t.id
                    ), '')), 'C')
            """)
            stats["updated"] = cur.rowcount

            # 4. Create GIN index
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tracks_search_vector
                ON tracks USING GIN(search_vector)
            """)

        conn.commit()

    if progress_callback:
        progress_callback(stats["updated"], stats["total"],
                          f"Rebuilt search vectors for {stats['updated']} tracks")

    logger.info(f"Search vector rebuild complete: {stats}")
    return stats
