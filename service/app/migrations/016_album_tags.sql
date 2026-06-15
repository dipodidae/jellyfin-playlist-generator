-- 016_album_tags.sql
-- Unified album-level tag/genre store (P2). Collects genres/tags from all
-- sources (Last.fm, Discogs, MusicBrainz, Metal Archives) into one table
-- that the scoring layer (P3) can read uniformly. Pure collection — no
-- behavioural change on its own.

CREATE TABLE IF NOT EXISTS album_tags (
    album_id UUID NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    source   VARCHAR(20) NOT NULL,   -- lastfm | discogs | musicbrainz | metal_archives
    tag      VARCHAR NOT NULL,        -- normalized: lowercased, trimmed
    kind     VARCHAR(10) NOT NULL DEFAULT 'genre',  -- genre | style | tag
    weight   REAL,                    -- source-native weight/count, nullable
    position INTEGER,                 -- source ordering where available, nullable
    PRIMARY KEY (album_id, source, kind, tag)
);

CREATE INDEX IF NOT EXISTS idx_album_tags_album ON album_tags(album_id);
CREATE INDEX IF NOT EXISTS idx_album_tags_tag   ON album_tags(tag);
