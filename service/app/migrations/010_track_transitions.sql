-- Migration 010: Track transition memory table
-- Records consecutive track pairs from generated playlists for future learning.

CREATE TABLE IF NOT EXISTS track_transitions (
    track_a_id  UUID NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    track_b_id  UUID NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    play_count  INT NOT NULL DEFAULT 1,
    skip_count  INT NOT NULL DEFAULT 0,
    last_used   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (track_a_id, track_b_id)
);

CREATE INDEX IF NOT EXISTS idx_track_transitions_a ON track_transitions(track_a_id);
CREATE INDEX IF NOT EXISTS idx_track_transitions_b ON track_transitions(track_b_id);
