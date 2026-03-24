-- Migration 011: Genre Manifold System
-- Probabilistic genre identity vectors per track + genre centroid embeddings.

CREATE TABLE IF NOT EXISTS track_genre_probabilities (
    track_id    UUID PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    genre_probs JSONB NOT NULL DEFAULT '{}',
    top_genre   TEXT,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tgp_top_genre ON track_genre_probabilities(top_genre);

CREATE TABLE IF NOT EXISTS genre_manifold (
    genre_family TEXT PRIMARY KEY,
    centroid     VECTOR(384),
    track_count  INTEGER NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
