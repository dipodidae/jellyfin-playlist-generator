-- 015_jellyfin_date_applied.sql — idempotency ledger for the Jellyfin release-date fixer.
-- Records which app albums have already had their original release date written to
-- Jellyfin (and at what year), so subsequent fixer runs skip them entirely and only
-- process new/changed albums (short maintenance bursts).
CREATE TABLE IF NOT EXISTS jellyfin_date_applied (
    album_id          UUID PRIMARY KEY REFERENCES albums(id) ON DELETE CASCADE,
    jellyfin_album_id TEXT,
    applied_year      INTEGER,
    applied_at        TIMESTAMPTZ DEFAULT now()
);
