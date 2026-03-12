-- Migration 009: Add BM25 full-text search vector to tracks table
-- This enables hybrid retrieval (semantic + keyword) for niche genre prompts.

ALTER TABLE tracks ADD COLUMN IF NOT EXISTS search_vector tsvector;

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
        SELECT string_agg(lt.name, ' ')
        FROM lastfm_tags lt
        JOIN track_lastfm_tags tlt ON lt.id = tlt.tag_id
        WHERE tlt.track_id = t.id
        ORDER BY tlt.weight DESC
        LIMIT 20
    ), '')), 'B');

CREATE INDEX IF NOT EXISTS idx_tracks_search_vector
ON tracks USING GIN(search_vector);
