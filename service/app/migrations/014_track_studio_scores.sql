-- 014_track_studio_scores.sql — studio-vs-live version scoring (Phase D)
CREATE TABLE IF NOT EXISTS track_studio_scores (
    track_id     UUID PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    version_type TEXT,
    studio_score REAL,
    computed_at  TIMESTAMPTZ DEFAULT now()
);
