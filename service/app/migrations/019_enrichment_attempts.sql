-- 019_enrichment_attempts.sql
-- Negative caching for enrichment passes that select "rows still missing X".
--
-- The bug this fixes, measured 2026-09-16: the Last.fm album-tag pass selected
--     FROM albums WHERE NOT EXISTS (album_tags ... source='lastfm')
--     ORDER BY id LIMIT 300
-- and only wrote a row when Last.fm actually returned tags. Once the first 300
-- albums by id were all ones Last.fm has no tags for, the candidate set stopped
-- changing, so every hourly run re-selected the SAME 300, fetched them again,
-- wrote nothing, and exited 0. 6,332 albums were outstanding and 6,032 of them
-- had never been attempted even once. Same shape in the release-date pass.
--
-- Recording the ATTEMPT (not just the success) is what makes the window
-- rotate: order by attempted_at NULLS FIRST and every candidate is tried once
-- before any is tried twice.
CREATE TABLE IF NOT EXISTS enrichment_attempts (
    scope        VARCHAR(40) NOT NULL,   -- lastfm_album_tags | lastfm_track | release_dates
    entity_id    UUID NOT NULL,          -- album_id or track_id, per scope
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempts     INTEGER NOT NULL DEFAULT 1,
    found        BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (scope, entity_id)
);

-- The ordering index for the "least recently attempted first" sweep.
CREATE INDEX IF NOT EXISTS idx_enrichment_attempts_sweep
    ON enrichment_attempts (scope, attempted_at);
